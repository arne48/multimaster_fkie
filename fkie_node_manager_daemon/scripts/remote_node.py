#!/usr/bin/env python3

import os
import shlex
import socket
import subprocess
import sys
import time
import argparse

from fkie_multimaster_msgs.logging.logging import Log

from fkie_node_manager_daemon import host as nmdhost
from fkie_node_manager_daemon import screen

from fkie_node_manager_daemon.settings import RESPAWN_SCRIPT

if os.environ['ROS_VERSION'] == "1":
    from fkie_master_discovery.common import masteruri_from_ros
    from fkie_node_manager_daemon.common import isstring
    from rosgraph.network import get_local_addresses
    try:
        from fkie_node_manager import get_ros_home
        from fkie_node_manager import Settings
        from fkie_node_manager import StartHandler
        from fkie_node_manager import StartException
    except Exception:
        from fkie_node_manager.reduced_nm import get_ros_home
        from fkie_node_manager.reduced_nm import Settings
        from fkie_node_manager.reduced_nm import StartHandler
        from fkie_node_manager.reduced_nm import StartException


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Start nodes remotely using the host ROS configuration',
        epilog="Fraunhofer FKIE 2022")

    parser.add_argument('--node_type',
                        required=True,
                        help='Type of the node to run')
    parser.add_argument('--node_name',
                        required=True,
                        help='The name of the node (with namespace)')
    parser.add_argument('--package',
                        required=True,
                        help='Package containing the node. If no node_name specified returns the package path or raise an exception, if the package was not found.')
    parser.add_argument('--node_respawn',
                        default=None,
                        help='respawn the node, if it terminate unexpectedly')
    parser.add_argument('--show_screen_log',
                        default=None,
                        help='Shows the screen log of the given node')
    parser.add_argument('--tail_screen_log',
                        default=None,
                        help='Tail the screen log of the given node')
    parser.add_argument('--show_ros_log',
                        default=None,
                        help='Shows the ros log of the given node')
    parser.add_argument('--ros_log_path',
                        default=None,
                        help='request for the path of the ros logs')
    parser.add_argument('--ros_logs',
                        default=None,
                        help='request for the list of available log nodes')
    parser.add_argument('--delete_logs',
                        default=None,
                        help='Delete the log files of the given node')
    parser.add_argument('--prefix',
                        default="",
                        help='Prefix used to run a node')
    parser.add_argument('--pidkill',
                        default=None,
                        help='kill the process with given pid')
    parser.add_argument('--masteruri',
                        default=None,
                        help='the ROS MASTER URI for started node')

    args, additional_args = parser.parse_known_args()

    Log.info("remote_node.py", "\nArguments: \n", args, "\n\nAdditional Arguments:\n", additional_args, "\n")

    return parser, args, additional_args


def getCwdArg(arg, argv):
    for a in argv:
        key, sep, value = a.partition(':=')
        if sep and arg == key:
            return value
    return None


def rosconsole_cfg_file(package, loglevel='INFO'):
    result = os.path.join(screen.LOG_PATH, '%s.rosconsole.config' % package)
    with open(result, 'w') as cfg_file:
        cfg_file.write('log4j.logger.ros=%s\n' % loglevel)
        cfg_file.write('log4j.logger.ros.roscpp=INFO\n')
        cfg_file.write('log4j.logger.ros.roscpp.superdebug=WARN\n')
    return result


def remove_src_binary(cmdlist):
    result = []
    count = 0
    if len(cmdlist) > 1:
        for c in cmdlist:
            if c.find('/src/') == -1:
                result.append(c)
                count += 1
    else:
        result = cmdlist
    if count > 1:
        # we have more binaries in src directory
        # aks the user
        result = cmdlist
    return result


def run_ROS1_node(package, executable, name, args, prefix='', respawn=False, masteruri=None, loglevel=''):
    '''
    Runs a ROS1 node. Starts a roscore if needed.
    '''
    import roslib

    if not masteruri:
        masteruri = masteruri_from_ros()

    # start roscore, if needed
    StartHandler._prepareROSMaster(masteruri)

    # start node
    try:
        cmd = roslib.packages.find_node(package, executable)
    except roslib.packages.ROSPkgException as e:
        # multiple nodes, invalid package
        raise StartException(str(e))

    # handle different result types str or array of string (electric / fuerte)
    if isstring(cmd):
        cmd = [cmd]
    if cmd is None or len(cmd) == 0:
        raise StartException(' '.join(
            [executable, 'in package [', package, '] not found!\n\nThe package was created?\nIs the binary executable?\n']))

    # create string for node parameter. Set arguments with spaces into "'".
    cmd = remove_src_binary(cmd)
    node_params = ' '.join(''.join(["'", a, "'"]) if a.find(' ') > -1 else a for a in args[1:])

    Log.info(screen.get_cmd(name), node_params)

    cmd_args = [screen.get_cmd(name),
                RESPAWN_SCRIPT if respawn else '', prefix, cmd[0], node_params]
    Log.info('run on remote host:', ' '.join(cmd_args))

    # determine the current working path
    arg_cwd = getCwdArg('__cwd', args)
    cwd = get_ros_home()
    if not (arg_cwd is None):
        if arg_cwd == 'ROS_HOME':
            cwd = get_ros_home()
        elif arg_cwd == 'node':
            cwd = os.path.dirname(cmd[0])

    # set the masteruri to launch with other one master
    new_env = dict(os.environ)
    new_env['ROS_MASTER_URI'] = masteruri
    ros_hostname = nmdhost.get_ros_hostname(masteruri)
    if ros_hostname:
        addr = socket.gethostbyname(ros_hostname)
        if addr in set(ip for ip in get_local_addresses()):
            new_env['ROS_HOSTNAME'] = ros_hostname
    if loglevel:
        new_env['ROSCONSOLE_CONFIG_FILE'] = rosconsole_cfg_file(package)
    subprocess.Popen(shlex.split(str(' '.join(cmd_args))),
                     cwd=cwd, env=new_env)
    if len(cmd) > 1:
        Log.warn(
            'Multiple executables were found! The first one was started! Executables:\n%s', str(cmd))


def run_ROS2_node(package, executable, name, args, prefix='', respawn=False):
    '''
    Runs a ROS2 node
    '''

    cmd = f'ros2 run {package} {executable} --ros-args --remap __name:={name}'
    node_params = ' '.join(''.join(["'", a, "'"]) if a.find(' ') > -1 else a for a in args[1:])

    Log.info(screen.get_cmd(name), node_params)

    cmd_args = [screen.get_cmd(name),
                RESPAWN_SCRIPT if respawn else '', prefix, cmd, node_params]

    screen_command = ' '.join(cmd_args)

    Log.info('run on remote host:', screen_command)
    subprocess.Popen(shlex.split(screen_command), env=dict(os.environ))


def main(argv=sys.argv):
    parser, args, additional_args = parse_arguments()

    try:
        print_help = True

        if args.show_screen_log:
            logfile = screen.get_logfile(node=args.show_screen_log)
            if not os.path.isfile(logfile):
                raise Exception('screen logfile not found for: %s' %
                                args.show_screen_log)
            cmd = ' '.join([Settings.LOG_VIEWER, str(logfile)])
            Log.info(cmd)
            p = subprocess.Popen(shlex.split(cmd))
            p.wait()
            print_help = False

        if args.tail_screen_log:
            logfile = screen.get_logfile(node=args.tail_screen_log)
            if not os.path.isfile(logfile):
                raise Exception('screen logfile not found for: %s' %
                                args.tail_screen_log)
            cmd = ' '.join(['tail', '-f', '-n', '25', str(logfile)])
            Log.info(cmd)
            p = subprocess.Popen(shlex.split(cmd))
            p.wait()
            print_help = False

        elif args.show_ros_log:
            logfile = screen.get_ros_logfile(node=args.show_ros_log)
            if not os.path.isfile(logfile):
                raise Exception('ros logfile not found for: %s' %
                                args.show_ros_log)
            cmd = ' '.join([Settings.LOG_VIEWER, str(logfile)])
            Log.info(cmd)
            p = subprocess.Popen(shlex.split(cmd))
            p.wait()
            print_help = False

        elif args.ros_log_path:
            if args.ros_log_path == '[]':
                Log.info(get_ros_home())
            else:
                Log.info(screen.get_logfile(node=args.ros_log_path))
            print_help = False

        elif args.delete_logs:
            logfile = screen.get_logfile(node=args.delete_logs)
            pidfile = screen.get_pidfile(node=args.delete_logs)
            roslog = screen.get_ros_logfile(node=args.delete_logs)
            if os.path.isfile(logfile):
                os.remove(logfile)
            if os.path.isfile(pidfile):
                os.remove(pidfile)
            if os.path.isfile(roslog):
                os.remove(roslog)
            print_help = False

        elif args.node_type and args.package and args.node_name:
            if os.environ['ROS_VERSION'] == "1":
                run_ROS1_node(args.package, args.node_type, args.node_name,
                              additional_args, args.prefix, args.node_respawn, args.masteruri)
            elif os.environ['ROS_VERSION'] == "2":
                run_ROS2_node(args.package, args.node_type, args.node_name,
                              additional_args, args.prefix, args.node_respawn)
            else:
                Log.error(f'Invalid ROS Version: {os.environ["ROS_VERSION"]}')

            print_help = False

        elif args.pidkill:
            import signal
            os.kill(int(args.pidkill), signal.SIGKILL)
            print_help = False

        if print_help:
            parser.print_help()
            time.sleep(3)

    except Exception as e:
        import traceback
        Log.error(traceback.format_exc())


if __name__ == '__main__':
    main()
