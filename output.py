import colorama as ca
import time

def error(text):
    print('[{}] {}'.format(time.strftime("%Y-%m-%d %H:%M:%S"), ca.Fore.RED + '[ FAIL ] ' + ca.Style.RESET_ALL + str(text)))

def warn(text):
    print('[{}] {}'.format(time.strftime("%Y-%m-%d %H:%M:%S"), ca.Fore.YELLOW + '[ WARN ] ' + ca.Style.RESET_ALL + str(text)))

def info(text):
    print('[{}] {}'.format(time.strftime("%Y-%m-%d %H:%M:%S"), ca.Fore.BLUE + '[ INFO ] ' + ca.Style.RESET_ALL + str(text)))

def core(text):
    print('[{}] {}'.format(time.strftime("%Y-%m-%d %H:%M:%S"), ca.Fore.MAGENTA + '[ CORE ] ' + ca.Style.RESET_ALL + str(text)))

def success(text):
    print('[{}] {}'.format(time.strftime("%Y-%m-%d %H:%M:%S"), ca.Fore.GREEN + '[  OK  ] ' + ca.Style.RESET_ALL + str(text)))

def get_time_format():
    return time.strftime("%Y-%m-%d %H:%M:%S")