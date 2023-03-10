#!/usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
import logging
import os
import re
import signal
import sys
import threading
import time

import favicon
import requests
import urllib3
import urllib3.exceptions
import yaml
from watchdog.events import (
    DirCreatedEvent,
    DirModifiedEvent,
    FileCreatedEvent,
    FileModifiedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer


class UnexpectedItemInManagedWorkdir(Exception):
    def __init__(
        self, path: str, message: str = "Unexpected item in managed work directory"
    ) -> None:
        self.path: str = path
        self.message: str = message
        super().__init__(self.message)


class UpdateKillnowTimeout(Exception):
    def __init__(
        self,
        message: str = "Timeout value exceeded waiting for thread to die",
    ) -> None:
        self.message: str = message
        super().__init__(self.message)


class GracefulKiller:
    kill_now: bool = False

    def __init__(self) -> None:
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, *arg) -> None:
        del arg
        self.kill_now = True


class UpdateWorker:
    def __init__(
        self,
        named_args: argparse.Namespace,
        threads_stop_timeout_seconds: float = 30.0,
        threads_kill_timeout_seconds: float = 30.0,
    ) -> None:
        self.named_args: argparse.Namespace = named_args
        self.threads_stop_timeout_seconds: float = threads_stop_timeout_seconds
        self.threads_kill_timeout_seconds: float = threads_kill_timeout_seconds

        self.threads: list[threading.Thread] = []
        self.threads_killnow_flag: threading.Event = threading.Event()

    def stopall(self, killnow: bool = False) -> None:
        if not self.threads:
            return

        if killnow:
            self.threads_killnow_flag.set()

        for thread in self.threads:
            if not self.threads_killnow_flag.is_set():
                thread.join(self.threads_stop_timeout_seconds)

                if thread.is_alive():
                    logging.error("Stop timeout exceeded. Falling back to killnow flag")
                    self.threads_killnow_flag.set()
                else:
                    return

            thread.join(self.threads_kill_timeout_seconds)

            if thread.is_alive():
                raise UpdateKillnowTimeout

            self.threads_killnow_flag.clear()
            return

    def run(self) -> None:
        if self.threads:
            self.stopall(killnow=True)

        thread: threading.Thread = threading.Thread(target=self.update)
        self.threads.append(thread)
        thread.start()

    def update(self) -> None:
        logging.info("Running update")

        clear_workdir(self.named_args.workdir)

        output_config: str = os.path.join(self.named_args.output, "assets/config.yml")

        data: dict = read_yaml(self.named_args.config)
        output_data: dict = read_yaml(output_config)

        if self.threads_killnow_flag.is_set():
            return

        service_update_threads: list[threading.Thread] = []
        for service_group in data["services"]:
            for service in service_group["items"]:
                thread: threading.Thread = threading.Thread(
                    target=self.update_service,
                    args=[service],
                )
                service_update_threads.append(thread)
                thread.start()

        for thread in service_update_threads:
            thread.join()

        if self.threads_killnow_flag.is_set():
            return

        if data != output_data:
            dump_yaml(data, output_config)

        logging.info("Finished update")

    def update_service(self, service: dict[str, str]) -> None:
        icons: list[favicon.Icon] = find_icons(service["url"], 2.0, self.named_args.verify_ssl)
        if not icons:
            return

        validated_icon: favicon.Icon | None = None
        for icon in icons:
            if test_url_is_image(icon.url, 2.0, self.named_args.verify_ssl):
                validated_icon = icon
                break

        if not validated_icon:
            logging.error(
                "No icons found for url of %s (%s) are reachable",
                service["name"],
                service["url"],
            )
            return

        stem: str = slugify(service["name"])
        name: str = ".".join([stem, validated_icon.format])

        path: str = os.path.join(self.named_args.workdir, name)

        i: int = 1
        while os.path.exists(path):
            stem_i: str = "_".join([stem, str(i)])
            name: str = ".".join([stem_i, validated_icon.format])

            path: str = os.path.join(self.named_args.workdir, name)
            i += 1

        download_successful: bool = download_binary(
            validated_icon.url, path, 2.0, self.named_args.verify_ssl
        )
        if download_successful:
            relpath: str = os.path.relpath(path, start=self.named_args.output)
            service["logo"] = relpath


class ConfigHandler(FileSystemEventHandler):
    def __init__(self, named_args: argparse.Namespace, update_worker: UpdateWorker) -> None:
        self.named_args: argparse.Namespace = named_args
        self.last_trigger_time: float = time.time()
        self.update_worker: UpdateWorker = update_worker

    def on_created(self, event: DirCreatedEvent | FileCreatedEvent) -> None:
        # Update on creation of files with basename of config in child path of config parent
        # Useful for k8s configmaps which are symlinks and do not produce file modification events
        dirname: str = os.path.dirname(self.named_args.config)
        name: str = os.path.basename(self.named_args.config)

        if event.is_directory:
            return

        if os.path.commonpath([event.src_path, dirname]) != dirname:
            return

        if os.path.basename(event.src_path) != name:
            return

        logging.info("%s : %s", event.event_type, event.src_path)

        self.update_worker.run()

    def on_modified(self, event: DirModifiedEvent | FileModifiedEvent) -> None:
        # Update on direct modification of config file
        if event.is_directory:
            return

        if event.src_path != self.named_args.config:
            return

        # "Debounce" filter prevents unnecessary double-updates from certain programs (e.g. VSCode)
        current_time: float = time.time()
        if str(event.src_path).find("~") == -1 and (current_time - self.last_trigger_time) > 1:
            self.last_trigger_time = current_time

            logging.info("%s : %s", event.event_type, event.src_path)

            self.update_worker.run()


def clear_workdir(workdir: str) -> None:
    # If subdirectory is found in work directory, halt deletion, otherwise continue
    try:
        subdirs: list[str] = next(os.walk(workdir, topdown=True, followlinks=False))[1]
        if subdirs:
            raise UnexpectedItemInManagedWorkdir(subdirs[0])
    except StopIteration:
        pass

    with os.scandir(workdir) as scandir:
        for item in scandir:
            if item.is_file():
                os.remove(item.path)


def download_binary(url: str, path: str, timeout_seconds: float, verify_ssl: bool) -> bool:
    logging.info("Downloading %s to %s", url, path)

    response: requests.Response = requests.get(
        url, timeout=timeout_seconds, stream=True, verify=bool(verify_ssl)
    )
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        logging.error(exc)
        return False

    with open(path, "wb") as stream:
        for chunk in response.iter_content(1024):
            stream.write(chunk)

    return True


def dump_yaml(config: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as stream:
        yaml.safe_dump(config, stream)


def find_icons(url: str, timeout_seconds: float, verify_ssl: bool) -> list[favicon.Icon]:
    try:
        icons: list[favicon.Icon] = favicon.get(
            url, timeout=timeout_seconds, verify=bool(verify_ssl)
        )
    except requests.exceptions.ConnectionError as exc:
        logging.error(exc)
        return []

    return icons


def parse_arguments() -> argparse.Namespace:
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default="/www/assets/source/config.yml",
        help="path to homer config file",
    )
    parser.add_argument(
        "-d",
        "--workdir",
        type=str,
        default="/www/assets/managed",
        help="path to managed work directory",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="/www",
        help="path to managed config file output",
    )
    parser.add_argument(
        "-D",
        "--daemon",
        type=int,
        choices=[0, 1],
        default=1,
        help="controls whether to enable daemon mode for watching config changes",
    )
    parser.add_argument(
        "--verify-ssl",
        type=int,
        choices=[0, 1],
        default=1,
        help="verify certificates for HTTPS connections",
    )

    args: argparse.Namespace = parser.parse_args()

    return args


def read_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def slugify(string: str) -> str:
    string = string.lower()
    # unify separators -> "_"
    string = re.sub(r"[ -.,;\"'&|/\\]", "_", string)
    # remove stacked separators e.g. "___" -> "_"
    string = re.sub(r"_{2,}", "_", string)
    # remove remaining invalid characters
    string = re.sub(r"[^a-z0-9_]", "", string)

    return string


def test_url_is_image(url: str, timeout_seconds: float, verify_ssl: bool) -> bool:
    image_formats: list[str] = ["image/png", "image/apng", "image/webp", "image/x-icon"]

    response: requests.Response = requests.get(
        url, timeout=timeout_seconds, verify=bool(verify_ssl)
    )

    if response.headers.get("Content-Type") in image_formats:
        return True
    else:
        return False


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    killer: GracefulKiller = GracefulKiller()

    args: argparse.Namespace = parse_arguments()

    logging.info("Using args: %s", args)

    if not bool(args.verify_ssl):
        # spam warnings -> 1 warning
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logging.warning("SSL verification disabled, certificate verification is strongly advised")

    worker: UpdateWorker = UpdateWorker(args)
    worker.run()

    if not bool(args.daemon):
        sys.exit()

    watch_paths: list[str | str] = [args.config, os.path.dirname(args.config)]

    event_handler: ConfigHandler = ConfigHandler(args, worker)

    observer: Observer = Observer()
    observers: list[Observer] = []

    logging.info("Listening for changes to %s", args.config)

    for watch_path in watch_paths:
        observer.schedule(event_handler, watch_path, recursive=True)
        observers.append(observer)
    observer.start()

    try:
        # Wait for kill signal from host to exit, otherwise run indefinitely
        while not killer.kill_now:
            time.sleep(1)
    finally:
        # ensure observers are stopped gracefully
        for observer in observers:
            observer.stop()
            observer.join()
        # ensure update thread is finished gracefully
        worker.stopall(killnow=False)


if __name__ == "__main__":
    main()
