#!/usr/bin/env python

import sys, os, time, atexit
from signal import SIGTERM
import syslog
from os.path import basename
from time import localtime, strftime

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

import utils.cloud_utils as cloud_utils


class Daemon(object):
    """
    Usage: subclass the Daemon class and override the run() method
    """

    def __init__(self, pidfile, monitorPidFile=None, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.pidfile = pidfile
        self.monitorPidFile = monitorPidFile
        self.primarypid = None
        self.monitorpid = None

    def daemonize(self):
        """
        do the UNIX double-fork magic, see Stevens' "Advanced 
        Programming in the UNIX Environment" for details (ISBN 0201563177)
        http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
        """
        try:
            pid = os.fork()
            if pid > 0:
                # exit first parent
                os._exit(0)
        except OSError, e:
            sys.stderr.write("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
            syslog.syslog("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
            os._exit(0)

        # decouple from parent environment
        os.chdir("/")
        os.setsid()
        os.umask(0)

        #        # do second fork
        #        try:
        #            pid = os.fork()
        #            if pid > 0:
        #                # exit from second parent
        #                os._exit(0)
        #        except OSError, e:
        #            sys.stderr.write("fork #2 failed: %d (%s)\n" % (e.errno, e.strerror))
        #            syslog.syslog("fork #2 failed: %d (%s)" % (e.errno, e.strerror))
        #            os._exit(0)

        # redirect standard file descriptors
        try:
            sys.stdout.flush()
        except:
            pass
        sys.stderr.flush()
        si = file(self.stdin, 'r')
        so = file(self.stdout, 'a+')
        se = file(self.stderr, 'a+', 0)
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())

        # write pidfile
        pid = str(os.getpid())

        if self.monitorPidFile is None:
            atexit.register(self.delpid, "Primary thread")
            self.primarypid = pid
            try:
                file(self.pidfile, 'w+').write("%s\n" % pid)
            except IOError:
                syslog.syslog("Unable to create pid file %s" % self.pidfile)

            self.run()
            os._exit(0)

        atexit.register(self.delmonitor)
        self.monitorpid = pid
        try:
            file(self.monitorPidFile, 'w+').write("%s\n" % pid)
            syslog.syslog("Created monitor's pid file %s with pid%s" % (self.monitorPidFile, pid))
        except IOError:
            syslog.syslog("Unable to create monitor's pid file %s" % self.monitorPidFile)

        self.monitor()
        os._exit(0)

    def delpid(self, thread):
        syslog.syslog("Primary daemon pid file deleted - by %s" % thread)
        if self.pidfile:
            os.remove(self.pidfile)

    def delmonitor(self, thread):
        syslog.syslog("Monitor daemon pid file deleted- by %s" % thread)
        if self.monitorPidFile:
            os.remove(self.monitorPidFile)

    def start(self):
        """
        Start the daemon
        """
        self.stop()
        # Start the daemon
        self.daemonize()

    def stop(self):
        """
        Stop the daemon
        """

        self.monitorpid = self.readpidAndDeleteFile(self.monitorPidFile)
        self.primarypid = self.readpidAndDeleteFile(self.pidfile)
        self.terminate(self.monitorpid)
        self.terminate(self.primarypid)

    def terminate(self, pid):
        if not pid:
            return
        if os.path.exists("/proc/%s" % pid) is False:
            syslog.syslog("Pid %s is already terminated" % pid)
            return
        syslog.syslog("Terminating pid %s" % pid)
        # Try killing the daemon process    
        try:
            while 1:
                os.kill(pid, SIGTERM)
                time.sleep(0.1)
        except OSError, err:
            err = str(err)
            if err.find("No such process") > 0:
                syslog.syslog("Pid %s removed with status %s" % (pid, str(err)))

    def readpidAndDeleteFile(self, pidfile):
        if pidfile is None:
            return None
            # Get the pid
        try:
            pf = file(pidfile, 'r')
            pid = int(pf.read().strip())
            pf.close()
        except IOError:
            pid = None
        if os.path.exists(pidfile):
            syslog.syslog("Daemon is removing %s" % pidfile)
            os.remove(pidfile)
        return pid

    def monitor(self):
        self.startPrimary()
        syslog.syslog("Monitor daemon with pid %s started to monitor pid %s..." % (self.monitorpid, self.primarypid))
        #        p,v = os.waitpid(int(self.primarypid), 0)
        #        syslog.syslog("Monitor Daemon - primary daemon retiurn codes %s %s" %(p,v))

        while True:
            time.sleep(5)
            try:
                if self.primarypid and os.path.exists("/proc/%s" % self.primarypid):
                    #                    syslog.syslog("%s: Monitoring pid %s..." % (self.monitorpid, self.primarypid))
                    pass
                else:
                    syslog.syslog("%s:  Primary Daemon %s aborted..." % self.primarypid)
                    self.startPrimary()
            except:
                if str(os.getpid()) != self.monitorpid:
                    syslog.syslog("Monitor task - ending pid is %s..." % str(os.getpid()))
                    self.exit()

    def startPrimary(self):
        # do another fork
        syslog.syslog("%s:b4 fork...." % os.getpid())
        try:
            pid = os.fork()
            if pid > 0:
                time.sleep(5)
                # os.wait after starting a new child to ensure that there is no defunct process left behind
                try:
                    syslog.syslog("%s: waiting .... child pid %s" % (os.getpid(), pid))
                    retval, status = os.waitpid(-1, 0)
                    syslog.syslog("return value is:%s status is:%s" % (retval, status))
                except:
                    cloud_utils.sys_log_exception(sys.exc_info())
                syslog.syslog("%s: Running parent" % (os.getpid()))
                time.sleep(5)
                # Get the pid
                try:
                    pf = file(self.pidfile, 'r')
                    self.primarypid = int(pf.read().strip())
                    pf.close()
                    syslog.syslog("Primary process started with pid %s" % self.primarypid)
                except IOError:
                    self.primarypid = None
                    syslog.syslog("Unable to restart daemon- exit")
                    os._exit(0)
                # back to monitor
                return
        except OSError, e:
            sys.stderr.write("fork #2 failed: %d (%s)\n" % (e.errno, e.strerror))
            syslog.syslog("fork #2 failed: %d (%s)" % (e.errno, e.strerror))
            self.exit()

        syslog.syslog("%s: Running child" % (os.getpid()))
        # decouple from parent environment
        os.chdir("/")
        os.setsid()
        os.umask(0)

        # redirect standard file descriptors
        sys.stdout.flush()
        sys.stderr.flush()
        si = file(self.stdin, 'r')
        so = file(self.stdout, 'a+')
        se = file(self.stderr, 'a+', 0)
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())

        syslog.syslog("%s: Starting work daemon..." % os.getpid())
        try:
            # write pidfile
            atexit.register(log_msg, self.delpid)
            pid = str(os.getpid())
            self.primarypid = pid
            try:
                file(self.pidfile, 'w+').write("%s\n" % pid)
            except IOError:
                syslog.syslog("Unable to create pid file %s" % self.pidfile)

            syslog.syslog("New primary daemon as pid:%s at file:%s" % (pid, self.pidfile))
            self.run()
        except:
            pass
        syslog.syslog("Exception! Unknown exit for pid:%s at file:%s" % (self.primarypid, self.pidfile))
        self.exit()

    def exit(self):
        """
        call exit for a graceful exit.  This will terminate the monitor task, if any.
        """
        syslog.syslog("Graceful exit for pid:%s at file:%s" % (self.primarypid, self.pidfile))
        self.stop()
        os._exit(0)

    def run(self):
        """
        You should override this method when you subclass Daemon. It will be called after the process has been
        daemonized by start() or restart().
        """
        syslog.syslog("Exception! Daemon ending as pid:%s at file:%s" % (self.primarypid, self.pidfile))
        self.exit()

    def cleanup(self):
        syslog.syslog("Cleaning up primary PID")


def log_msg(pid):
    syslog.syslog("Exception! Daemon ending as pid:%s" % pid)
