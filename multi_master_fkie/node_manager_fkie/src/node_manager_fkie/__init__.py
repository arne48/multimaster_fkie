#!/usr/bin/env python
# Software License Agreement (BSD License)
#
# Copyright (c) 2012, Fraunhofer FKIE/US, Alexander Tiderko
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of I Heart Engineering nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

__author__ = "Alexander Tiderko (Alexander.Tiderko@fkie.fraunhofer.de)"
__copyright__ = "Copyright (c) 2012 Alexander Tiderko, Fraunhofer FKIE/US"
__license__ = "BSD"
__version__ = "0.1"
__date__ = "2012-02-01"

import os
import sys
import signal
import socket
import threading

import roslib; roslib.load_manifest('node_manager_fkie')
import rospy

#PYTHONVER = (2, 7, 1)
#if sys.version_info < PYTHONVER:
#  print 'For full scope of operation this application requires python version > %s, current: %s' % (str(PYTHONVER), sys.version_info)

from ssh_handler import SSHhandler
from screen_handler import ScreenHandler
from start_handler import StartHandler, StartException 
from name_resolution import NameResolution

# set the cwd to the package of the node_manager_fkie to support the images
# in HTML descriptions of the robots and capabilities

PACKAGE_DIR = ''.join([roslib.packages.get_dir_pkg(os.path.abspath(os.path.dirname(sys.argv[0])))[0], os.path.sep])
os.chdir(PACKAGE_DIR)
ROBOTS_DIR = ''.join([PACKAGE_DIR, os.path.sep, 'images', os.path.sep])

CFG_PATH = ''.join(['.node_manager', os.sep])
'''@ivar: configuration path to store the history.'''

LESS = "/usr/bin/less -fKLnQrSU"
STARTER_SCRIPT = 'rosrun node_manager_fkie remote_nm.py'
'''
the script used on remote hosts to start new ROS nodes
'''
ARG_HISTORY_LENGTH = 5
''' 
the history for each required argument to load a launch file.
''' 
HOSTS_CACHE = {}
''' 
the cache directory to store the results of tests for local hosts.
@see: L{is_local()}
''' 

PARAM_CACHE = dict()
'''
the cache is used to store and recover the value for last entered parameter in parameter dialog.
'''

_lock = threading.RLock()

def terminal_cmd(cmd, title):
  '''
  Creates a command string to run with a terminal prefix
  @param cmd: the list with a command and args
  @type cmd: [str,..]
  @param title: the title of the terminal
  @type title: str
  @return: command with a terminal prefix
  @rtype:  str
  '''
  if os.path.isfile('/usr/bin/xterm'):
    return str(' '.join(['/usr/bin/xterm', '-geometry 112x35', '-title', str(title), '-e', ' '.join(cmd)]))
  elif os.path.isfile('/usr/bin/konsole'):
    return str(' '.join(['/usr/bin/konsole', '--noclose', '-title', str(title), '-e', ' '.join(cmd)]))

_ssh_handler = None
_screen_handler = None
_start_handler = None
_name_resolution = None
app = None

def ssh():
  '''
  @return: The SSH handler to handle the SSH connections
  @rtype: L{SSHhandler}
  '''
  global _ssh_handler
  return _ssh_handler

def screen():
  '''
  @return: The screen handler to the screens.
  @rtype: L{ScreenHandler}
  @see: U{http://linuxwiki.de/screen}
  '''
  global _screen_handler
  return _screen_handler

def starter():
  '''
  @return: The start handler to handle the start of new ROS nodes on local or 
  remote machines.
  @rtype: L{StartHandler}
  '''
  global _start_handler
  return _start_handler

def nameres():
  '''
  @return: The name resolution object translate the the name to the host or
  ROS master URI.
  @rtype: L{NameResolution}
  '''
  global _name_resolution
  return _name_resolution

def is_local(hostname):
  '''
  Test whether the given host name is the name of the local host or not.
  @param hostname: the name or IP of the host
  @type hostname: C{str}
  @return: C{True} if the hostname is local or None
  @rtype: C{bool}
  @raise Exception: on errors while resolving host
  '''
  if (hostname is None):
    return True

  if hostname in HOSTS_CACHE:
    if isinstance(HOSTS_CACHE[hostname], threading.Thread):
      return False
    return HOSTS_CACHE[hostname]
  
  try:
    machine_addr = socket.inet_aton(hostname)
    local_addresses = ['localhost'] + roslib.network.get_local_addresses()
    # check 127/8 and local addresses
    result = machine_addr.startswith('127.') or machine_addr in local_addresses
    HOSTS_CACHE[hostname] = result
    return result
  except socket.error:
    thread = threading.Thread(target=__is_local, args=((hostname,)))
    thread.daemon = True
    thread.start()
    HOSTS_CACHE[hostname] = thread
  return False

def __is_local(hostname):
  import roslib
  try:
    machine_addr = socket.gethostbyname(hostname)
  except socket.gaierror:
    HOSTS_CACHE[hostname] = False
    return
  local_addresses = ['localhost'] + roslib.network.get_local_addresses()
  # check 127/8 and local addresses
  result = machine_addr.startswith('127.') or machine_addr in local_addresses
  _lock.acquire(True)
  HOSTS_CACHE[hostname] = result
  _lock.release()


def get_ros_home():
  '''
  Returns the ROS HOME depending on ROS distribution API.
  @return: ROS HOME path
  @rtype: C{str}
  '''
  try:
    import rospkg.distro
    distro = rospkg.distro.current_distro_codename()
    if distro in ['electric', 'diamondback', 'cturtle']:
      import roslib.rosenv
      return roslib.rosenv.get_ros_home()
    else:
      import rospkg
      return rospkg.get_ros_home()
  except:
#    import traceback
#    print traceback.format_exc()
    import roslib.rosenv
    return roslib.rosenv.get_ros_home()


def masteruri_from_ros():
  '''
  Returns the master URI depending on ROS distribution API.
  @return: ROS master URI
  @rtype: C{str}
  '''
  try:
    import rospkg.distro
    distro = rospkg.distro.current_distro_codename()
    if distro in ['electric', 'diamondback', 'cturtle']:
      return roslib.rosenv.get_master_uri()
    else:
      import rosgraph
      return rosgraph.rosenv.get_master_uri()
  except:
    return roslib.rosenv.get_master_uri()

def finish(*arg):
  '''
  Callback called on exit of the ros node.
  '''
  # close all ssh sessions
  global _ssh_handler
  if not _ssh_handler is None:
    _ssh_handler.close()
  global app
  if not app is None:
    app.exit()


def setTerminalName(name):
  '''
  Change the terminal name.
  @param name: New name of the terminal
  @type name:  C{str}
  '''
  sys.stdout.write("".join(["\x1b]2;",name,"\x07"]))


def setProcessName(name):
  '''
  Change the process name.
  @param name: New process name
  @type name:  C{str}
  '''
  try:
    from ctypes import cdll, byref, create_string_buffer
    libc = cdll.LoadLibrary('libc.so.6')
    buff = create_string_buffer(len(name)+1)
    buff.value = name
    libc.prctl(15, byref(buff), 0, 0, 0)
  except:
    pass



#%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
#%%%%%%%%%%%%%                 MAIN                               %%%%%%%%
#%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

def main(name, anonymous=False):
  global CFG_PATH
  CFG_PATH = ''.join([get_ros_home(), os.sep, 'node_manager', os.sep])
  '''
  Creates and runs the ROS node.
  '''
  args = rospy.myargv(argv=sys.argv)
  # decide to show main or echo dialog
  if len(args) >= 4 and args[1] == '-t':
    name = ''.join([name, '_echo'])
    anonymous = True

  try:
    from PySide.QtGui import QApplication
    from PySide.QtCore import QTimer
  except:
    print >> sys.stderr, "please install 'python-pyside' package!!"
    sys.exit(-1)
  rospy.init_node(name, anonymous=anonymous, log_level=rospy.DEBUG)
  setTerminalName(rospy.get_name())
  setProcessName(rospy.get_name())

  # Initialize Qt
  global app
  app = QApplication(sys.argv)

  # decide to show main or echo dialog
  if len(args) >= 4 and args[1] == '-t':
    import echo_dialog
    mainForm = echo_dialog.EchoDialog(args[2], args[3])
  else:
    # initialize the global handler 
    global _ssh_handler
    global _screen_handler
    global _start_handler
    global _name_resolution
    _ssh_handler = SSHhandler()
    _screen_handler = ScreenHandler()
    _start_handler = StartHandler()
    _name_resolution = NameResolution()
  
    #start the gui
    import main_window
    mainForm = main_window.MainWindow()

  if not rospy.is_shutdown():
    mainForm.show()
    exit_code = -1
    rospy.on_shutdown(finish)
    exit_code = app.exec_()
    mainForm.finish()
#    finally:
#      print "final"
#      sys.exit(exit_code)
#      print "ex"
