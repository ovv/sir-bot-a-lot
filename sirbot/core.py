import asyncio
import logging
import functools
import pluggy
import importlib

from typing import Optional
from aiohttp import web

from sirbot.iterable_queue import IterableQueue
from sirbot.dispatcher import Dispatcher
from sirbot import hookspecs

logger = logging.getLogger('sirbot.core')


class SirBot:
    def __init__(self, config=None, *,
                 loop: Optional[asyncio.AbstractEventLoop] = None):

        self.loop = loop or asyncio.get_event_loop()
        self._tasks = {}
        self._dispatcher = None
        self._pm = None
        self.config = config or {}
        self._configure()

        self._clients = dict()

        logger.info('Initializing Sir-bot-a-lot')

        self._import_plugins()
        self._incoming_queue = IterableQueue(loop=self.loop)
        self._dispatcher = Dispatcher(self._pm, self.config, self.loop)

        self._app = web.Application(loop=self.loop,
                                    middlewares=(
                                        self._dispatcher.middleware_factory,))
        self._app.on_startup.append(functools.partial(self._start))
        self._app.on_cleanup.append(self._clean_background_tasks)

        self._initialize_clients()

    def _configure(self) -> None:
        """
        Configure Sirbot

=       :return: None
        """

        if 'loglevel' in self.config.get('core', {}):
            logger.setLevel(self.config['core']['loglevel'])
        if 'loglevel' in self.config:
            logging.getLogger('sirbot').setLevel(self.config['loglevel'])

    async def _start(self, app: web.Application) -> None:
        """
        Startup tasks
        """
        logger.info('Starting Sir-bot-a-lot ...')

        await self._connect_client()

        self._tasks['incoming'] = self.loop.create_task(
            self._read_incoming_queue())

        # Ensure that if futures exit on error, they aren't silently ignored.
        def print_if_err(f):
            """Logs the error if one occurred causing the task to exit."""
            if f.exception() is not None:
                logger.error('Task exited with error: %s', f.exception())

        for task in self._tasks.values():
            task.add_done_callback(print_if_err)

        logger.info('Sir-bot-a-lot started !')

    def _initialize_clients(self) -> None:
        """
        Initialize and start the clients
        """
        logger.debug('Initializing clients')
        clients = self._pm.hook.clients(loop=self.loop,
                                        queue=self._incoming_queue)
        if clients:
            for client in clients:
                self._clients[client[0]] = client[1]
                client[1].configure(self.config.get(client[0]),
                                    self._app.router)
        else:
            logger.error('No client found')

    async def _connect_client(self) -> None:
        logger.debug('Connecting clients')
        for name, client in self._clients.items():
            self._tasks[name] = self.loop.create_task(
                client.connect())

    def _import_plugins(self) -> None:
        """
        Import and register the plugins

        Most likely composed of a client and a dispatcher
        """
        logger.debug('Importing plugins')
        self._pm = pluggy.PluginManager('sirbot')
        self._pm.add_hookspecs(hookspecs)

        if 'core' in self.config and 'plugins' in self.config['core']:
            for plugin in self.config['core']['plugins']:
                p = importlib.import_module(plugin)
                self._pm.register(p)

    async def _clean_background_tasks(self, app) -> None:
        """
        Clean up the background tasks
        """
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), loop=self.loop)

    async def _read_incoming_queue(self) -> None:
        """
        Read from the incoming message queue
        """
        try:
            async for message in self._incoming_queue:
                logger.debug('Incoming message received from %s',
                             message[0])
                future = asyncio.ensure_future(
                    self._dispatcher.incoming_message(message[0], message[1]),
                    loop=self.loop)
                future.add_done_callback(self._set_queue_task_done)

        except asyncio.CancelledError:
            pass

    def _set_queue_task_done(self, *_):
        self._incoming_queue.task_done()

    @property
    def app(self) -> web.Application:
        """
        Return the composed aiohttp application
        """
        return self._app

    def run(self, host: str = '0.0.0.0', port: int = 8080):
        """
        Start the bot
        """
        web.run_app(self._app, host=host, port=port)
