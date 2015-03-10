#!/usr/bin/python2.7

import argparse
import time
import logging
import datetime
import signal
import sys
import os
import subprocess

logger = logging.getLogger("Benchmark.Master")

MSMR_ROOT = ''
cur_env = os.environ.copy()

def kill_previous_process(args):
    print "Killing previous related processes"
    cmd = 'sudo killall -9 worker-run.py server.out %s ' % (args.app)
    rcmd = 'parallel-ssh -v -p 3 -i -t 10 -h hostfile {command}'.format(
            command=cmd)
    p = subprocess.Popen(rcmd, shell=True, stdout=subprocess.PIPE)
    output, err = p.communicate()
    print output
    # killall criu-cr.py via sudo
    # bug02 worker2
    cmd = 'sudo killall -9 criu-cr.py &> /dev/null' 
    rcmd = 'parallel-ssh -v -p 1 -i -t 10 -h worker2 {command}'.format(
            command=cmd)
    p = subprocess.Popen(rcmd, shell=True, stdout=subprocess.PIPE)
    output, err = p.communicate()
    print output

def run_servers(args):
    cmd = "~/worker-run.py -a %s -x %d -p %d -k %d -c %s -m s -i 0 --sp %d --sd %d --scmd %s" % (
            args.app, args.xtern, args.proxy, args.checkpoint,
            args.msmr_root_server, args.sp, args.sd, args.scmd)
    print "replaying server master node command: "

    rcmd = "parallel-ssh -v -p 1 -i -t 10 -h head \"%s\"" % (cmd)
    print rcmd
    # Start the head node first
    p = subprocess.Popen(rcmd, shell=True, stdout=subprocess.PIPE)
    output, err = p.communicate()
    print output

    if args.proxy == 0:
        return

    for node_id in xrange(1, 3):
        wcmd = "~/worker-run.py -a %s -x %d -p %d -k %d -c %s -m r -i %d --sp %d --sd %d --scmd %s" % (
                args.app, args.xtern, args.proxy, args.checkpoint,
                args.msmr_root_server, node_id, args.sp, args.sd, args.scmd)
        rcmd_workers = "parallel-ssh -v -p 1 -i -t 10 -h worker%d \"%s\"" % (
                node_id, wcmd)
        print "Master: replaying master node command: "
        print rcmd_workers
        # Start the secondary nodes one by one
        p = subprocess.Popen(rcmd_workers, shell=True, stdout=subprocess.PIPE)
        output, err = p.communicate()
        print output

def restart_head(args):
    #cmd = '"~/head-restart.py"'
    cmd = 'sudo killall -9 server.out'
    rcmd_head = 'parallel-ssh -v -p 1 -i -t 10 -h head {command}'.format(
        command=cmd)
    p = subprocess.Popen(rcmd_head, shell=True, stdout=subprocess.PIPE)
    output, err = p.communicate()
    print output

def run_clients(args):
    cur_env['LD_PRELOAD'] = MSMR_ROOT + '/libevent_paxos/client-ld-preload/libclilib.so'
    if args.proxy == 1:
        cmd = '$MSMR_ROOT/apps/apache/install/bin/ab -n 10 -c 10 http://128.59.17.171:9000/'
    else:
        cmd = '$MSMR_ROOT/apps/apache/install/bin/ab -n 10 -c 10 http://128.59.17.171:8080/'
    p = subprocess.Popen(cmd, env=cur_env, shell=True, stdout=subprocess.PIPE)
    output, err = p.communicate()
    print output
    
def run_clients2(args):
    cur_env['LD_PRELOAD'] = MSMR_ROOT + '/libevent_paxos/client-ld-preload/libclilib.so'
    cmd = '$MSMR_ROOT/apps/apache/install/bin/ab -n 10 -c 10 http://128.59.17.172:9001/'
    p = subprocess.Popen(cmd, env=cur_env, shell=True, stdout=subprocess.PIPE)
    output, err = p.communicate()
    print output

# note: must use sudo
# we run criu on node 2(bug02), so parallel-ssh should -h worker2
def run_criu(args):
    shcmd = "sudo ~/criu-cr.py -s %s -t %d &> ~/criu-cr.log" % (args.app, args.checkpoint_period)
    psshcmd = "parallel-ssh -v -p 1 -i -t 5 -h worker2 \"%s\""%(shcmd)
    print "Master: replaying master node command: "
    print psshcmd
    p = subprocess.Popen(psshcmd, shell=True, stdout=subprocess.PIPE)
    '''
    # below is for debugging
    output, err = p.communicate()
    print output
    if "FAILURE" in output:
        print "killall directly"
        kill_previous_process(args) 
        sys.exit(0)
    '''

def main(args):
    """
    Main module of master.py
    """

    # Read param file

    # Create directory for storing logs 
    #log_name =  datetime.datetime.now().strftime("%Y%m%d-%H-%M-%S")
    #log_dir = "%s%s-%s" % (param["LOGDIR"], options.identifier, log_name)

    #Utils.mkdir(log_dir)
    
    #console_log = "%s/console.log" % log_dir

    # Killall the previous experiment
    kill_previous_process(args) 

    run_servers(args) 
    time.sleep(10)

    if args.checkpoint == 1:
        # run CRIU on bug02(Node 2)
	run_criu(args)
	# make sure wait for at least 20s before running client
	# to let CRIU run in the appropriate environment
	# rest assured. real server and libevent_paxos still run normally without influence
	# even if when the CRIU does dump work, beacuse CRIU does dump and then let the
	# checkpointed process run again will be finished in a flash, about 20~60ms
	time.sleep(20)

    run_clients(args)
    time.sleep(5)

    if args.proxy == 1:
        restart_head(args)
        time.sleep(20)

        run_clients2(args)

    kill_previous_process(args) 


###############################################################################
# Main - Parse command line options and invoke main()   
if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Explauncher(master)')

    parser.add_argument('-a', type=str, dest="app", action="store",
            help="Name of the application. e.g. microbenchmark.")
    parser.add_argument('-x', type=int, dest="xtern", action="store",
            help="Whether xtern is enabled.")
    parser.add_argument('-p', type=int, dest="proxy", action="store",
            help="Whether proxy is enabled.")
    parser.add_argument('-k', type=int, dest="checkpoint", action="store",
            help="Whether checkpointing on replicas is enabled.")
    parser.add_argument('-t', type=int, dest="checkpoint_period", action="store",
            help="Period of CRIU checkpoint")
    parser.add_argument('-c', type=str, dest="msmr_root_client", action="store",
            help="The directory of m-smr.")
    parser.add_argument('-s', type=str, dest="msmr_root_server", action="store",
            help="The directory of m-smr.")
    parser.add_argument('--sp', type=int, dest="sp", action="store",
            help="Schedule with paxos.")
    parser.add_argument('--sd', type=int, dest="sd", action="store",
            help="Schedule with DMT.")
    parser.add_argument('--scmd', type=str, dest="scmd", action="store",
            help="The command to execute the real server.")

    args = parser.parse_args()
    print "Replaying parameters:"
    print "App : " + args.app
    print "xtern : " + str(args.xtern)
    print "checkpoint : " + str(args.checkpoint)
    print "checkpoint_period : " + str(args.checkpoint_period)
    print "MSMR_ROOT : " + args.msmr_root_client

    main_start_time = time.time()

    MSMR_ROOT = args.msmr_root_client
    main(args)

    main_end_time = time.time()

    logger.info("Total time : %f sec", main_end_time - main_start_time)
