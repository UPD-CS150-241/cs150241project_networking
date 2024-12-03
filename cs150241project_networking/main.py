from __future__ import annotations
import threading
from websockets import ConnectionClosed
from websockets.sync.connection import Connection
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


class PlayerIdManager:
    def __init__(self):
        self._pid: PlayerId | None = None
        self._pid_condvar = threading.Condition()

    @property
    def pid_ready(self) -> bool:
        return self._pid is not None

    def set_pid(self, pid: PlayerId) -> None:
        with self._pid_condvar:
            self._pid = pid
            self._pid_condvar.notify_all()

    def wait_for_pid(self) -> PlayerId:
        with self._pid_condvar:
            self._pid_condvar.wait_for(lambda: self.pid_ready)
            assert self._pid is not None

            return self._pid


class CS150241ProjectNetworking:
    def __init__(self):
        self._pid = PlayerIdManager()

        self._send_queue: list[Message] = []
        self._recv_queue: list[Message] = []

        self._send_condvar = threading.Condition()
        self._recv_condvar = threading.Condition()

        self._exit_signal = threading.Event()

    def close_all_threads(self) -> None:
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

    def sync_recv_loop(self, websocket: ClientConnection) -> None:
        logger.debug('Thread: sync_recv_loop')

        while not self._exit_signal.is_set():
            logger.debug("Trying to recv from websocket (sync_recv_loop)")

            try:
                raw = websocket.recv()
            except ConnectionClosed:
                logger.info("Connection closed; ending recv loop")
                self.close_all_threads()
                break

            message = Message.from_raw(str(raw))

            logging.info(f"Queueing into recv queue: {message}")

            with self._recv_condvar:
                self._recv_queue.append(message)
                self._recv_condvar.notify_all()

        logger.info("Recv loop is done")

    def sync_send_loop(self, websocket: ClientConnection) -> None:
        logger.debug('Thread: sync_send_loop')
        is_send_loop_running = True

        while is_send_loop_running and not self._exit_signal.is_set():
            logger.debug("Trying to acquire send lock (sync_send_loop)")
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
                        websocket.send(message.as_sendable())
                    except ConnectionClosed:
                        logger.info("Connection closed; ending send loop")
                        self.close_all_threads()
                        is_send_loop_running = False
                        break

        logger.info("Send loop is done")

    def send(self, payload: str) -> None:
        logger.debug("Trying to acquire send lock (send)")
        with self._send_condvar:
            logger.debug("Acquired send lock; will wait for PID (send)")
            message = Message(source=self._pid.wait_for_pid(), payload=payload)
            logger.debug("Got PID")

            logging.info(f"Queueing for sending: {message}")
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

    def run_thread(self, ip_addr: str, port: int) -> threading.Thread:
        t = threading.Thread(
            target=self._sync_main, args=(ip_addr, port), daemon=True)
        t.start()

        return t

    def _set_pid_from_message(self, websocket: Connection) -> None:
        logger.debug("Waiting for initial PID message")
        raw = websocket.recv()
        message = Message.from_raw(str(raw))
        logger.debug("Received initial PID message")
        logger.debug('Trying to set PID')
        self._pid.set_pid(message.source)
        logger.debug('Successfully set PID')

    def _sync_main(self, ip_addr: str, port: int) -> None:
        logger.debug('Thread: Networking main')
        with connect(f"ws://{ip_addr}:{port}") as websocket:
            self._set_pid_from_message(websocket)

            t1 = threading.Thread(target=self.sync_send_loop,
                                  args=(websocket,), daemon=True)
            t2 = threading.Thread(target=self.sync_recv_loop,
                                  args=(websocket,), daemon=True)

            t1.start()
            t2.start()

            t1.join()
            t2.join()


if __name__ == "__main__":
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)s | %(thread_id)d | %(message)s'))
    handler.addFilter(thread_id_filter)
    logger.addHandler(handler)
    logger.setLevel('INFO')

    networking = CS150241ProjectNetworking()
    thread = networking.run_thread('localhost', 15000)

    logging.info('Thread: Client')
    print('Client trying to send payload')
    networking.send("PAYLOAD 1")
    networking.send("PAYLOAD 2")
    networking.send("PAYLOAD 3")

    print('Client calling recv...')
    for m in networking.recv():
        print('Client recv loop:', m)

    print('Client done')

    thread.join()
