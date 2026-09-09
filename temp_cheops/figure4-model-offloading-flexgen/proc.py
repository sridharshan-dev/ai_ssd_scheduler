import subprocess
import psutil  # not installed by default
import time


def exec_cmd(cmd, run=False):
    print(cmd)
    if not run:
        return

    res = subprocess.run(cmd, stderr=subprocess.STDOUT, shell=True, check=True)


def exec_cmd_background(cmd, run=False):
    print(cmd)
    if not run:
        return

    p = subprocess.Popen(cmd, stderr=subprocess.STDOUT, shell=True)
    return p


def kill_process_and_children(pid):
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            child.kill()
        parent.kill()
    except psutil.NoSuchProcess:
        pass

    time.sleep(1)

    # Check if the process is still running
    status = True
    while status:
        status = False
        try:
            status = status or (parent.status() == 'running')
        except:
            pass
        for child in children:
            try:
                status = status or (child.status() == 'running')
            except:
                pass
