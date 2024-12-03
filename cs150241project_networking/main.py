from __future__ import annotations
import threading
from websockets import ConnectionClosed
from websockets.sync.client import connect, ClientConnection
from typing import NewType, Generator
from dataclasses import dataclass
import logging


logger = logging.getLogger()

PlayerId = NewType('PlayerId', int)


def thread_id_filter(record: logging.LogRecord) -> logging.LogRecord:
    record.thread_id = threading.get_native_id()
    return record


@dataclass(frozen=True)
class Message:
    source: PlayerId
    payload: str

    @classmethod
    def from_raw(cls, raw: str) -> Message:
        tokens = raw.split(' ', maxsplit=1)
        source = PlayerId(int(tokens[0]))
        payload = tokens[1]

        return Message(source=source, payload=payload)

    def as_sendable(self) -> str:
        return f'{self.source} {self.payload}'


class CS150241ProjectNetworking:
    @classmethod
    def connect(cls, ip_addr: str, port: int) -> CS150241ProjectNetworking:
        websocket = connect(f"ws://{ip_addr}:{port}")

        logger.debug("Waiting for initial PID message")
        raw = websocket.recv()
        message = Message.from_raw(str(raw))
        logger.debug("Received initial PID message")
        player_id = message.source

        ret = CS150241ProjectNetworking(websocket, player_id)
        ret.start()

        return ret

    def __init__(self, websocket: ClientConnection, player_id: PlayerId):
        self._websocket = websocket
        self._player_id = player_id

        self._send_queue: list[Message] = []
        self._recv_queue: list[Message] = []

        self._send_condvar = threading.Condition()
        self._recv_condvar = threading.Condition()

        self._exit_signal = threading.Event()

    @property
    def player_id(self):
        return self._player_id

    def start(self):
        t1 = threading.Thread(target=self._sync_send_loop, daemon=True)
        t2 = threading.Thread(target=self._sync_recv_loop, daemon=True)

        t1.start()
        t2.start()

    def send(self, payload: str) -> None:
        logger.debug("Trying to acquire send lock (send)")
        with self._send_condvar:
            message = Message(source=self.player_id, payload=payload)
            logging.info(
                f"Acquired send lock; queueing for sending: {message}")

            self._send_queue.append(message)
            self._send_condvar.notify_all()

    def recv(self) -> Generator[Message, None, None]:
        logger.debug("Trying to acquire recv lock (recv)")
        with self._recv_condvar:
            logger.debug("Acquired recv lock (recv); yielding recv queue data")

            while self._recv_queue:
                message = self._recv_queue.pop(0)
                logging.info(f"Popping from recv queue: {message}")
                yield message

    def _close_all_threads(self) -> None:
        self._exit_signal.set()

        if self._send_condvar.acquire(blocking=False):
            logging.debug("Notifying all waiting on send condvar")
            self._send_condvar.notify_all()
            self._send_condvar.release()
        else:
            logging.debug("Failed to notify all waiting on send condvar")

        if self._recv_condvar.acquire(blocking=False):
            logging.debug("Notifying all waiting on recv condvar")
            self._recv_condvar.notify_all()
            self._recv_condvar.release()
        else:
            logging.debug("Failed to notify all waiting on recv condvar")

    def _sync_recv_loop(self) -> None:
        logger.debug('Thread: _sync_recv_loop')

        while not self._exit_signal.is_set():
            logger.debug("Trying to recv from websocket (_sync_recv_loop)")

            try:
                raw = self._websocket.recv()
            except ConnectionClosed:
                logger.info("Connection closed; ending recv loop")
                self._close_all_threads()
                break

            message = Message.from_raw(str(raw))

            logging.info(f"Queueing into recv queue: {message}")

            with self._recv_condvar:
                self._recv_queue.append(message)
                self._recv_condvar.notify_all()

        logger.info("Recv loop is done")

    def _sync_send_loop(self) -> None:
        logger.debug('Thread: _sync_send_loop')
        is_send_loop_running = True

        while is_send_loop_running and not self._exit_signal.is_set():
            logger.debug("Trying to acquire send lock ()sync_send_loop)")
            with self._send_condvar:
                logger.debug(
                    "Acquired send lock (sync_send_loop); will wait for send queue data")

                self._send_condvar.wait_for(lambda: len(self._send_queue) > 0
                                            or self._exit_signal.is_set())

                if self._exit_signal.is_set():
                    logger.info("Send loop is exiting due to exit signal")
                    break

                logger.debug("send queue data found; will process")

                while self._send_queue:
                    message = self._send_queue.pop()
                    logging.info(f"Sending: {message}")

                    try:
                        self._websocket.send(message.as_sendable())
                    except ConnectionClosed:
                        logger.info("Connection closed; ending send loop")
                        self._close_all_threads()
                        is_send_loop_running = False
                        break

        logger.info("Send loop is done")


if __name__ == "__main__":
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)s | %(thread_id)d | %(message)s'))
    handler.addFilter(thread_id_filter)
    logger.addHandler(handler)
    logger.setLevel('INFO')

    networking = CS150241ProjectNetworking.connect('localhost', 15000)

    logging.info(f'Client is Player {networking.player_id}')
    print('Client trying to send payload')
    networking.send("PAYLOAD 1")
    networking.send("PAYLOAD 2")
    networking.send("PAYLOAD 3")

    print('Client calling recv...')
    for m in networking.recv():
        print('Client recv loop:', m)

    print('Client done')
