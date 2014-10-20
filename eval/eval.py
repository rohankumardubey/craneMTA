#!/usr/bin/env python

import threading
import ConfigParser
import re
import argparse
import sys
import logging
import os
import subprocess
from signal import signal

def getMsmrDefaultOptions():
	default = {}
	return default

def getConfigFullPath(config_file):
	try:
		with open(config_file) as f: pass
	except IOError as e:
		logging.warning("'%s' does not exist" % config_file)
		return None
	return os.path.abspath(config_file)

def readConfigFile(config_file):
	try:
		newConfig = ConfigParser.ConfigParser({"REPEATS":"1",
						       "INPUTS":"",
						       "EXPORT":"",
						       "TEST_NAME":"",
						       "NO":"",
						       "LOG_SUFFIX":".log",
						       "SLEEP_TIME":"5",
						       "SECONDARIES_SIZE":"2",
						       "SERVER_CONFIG":"../libevent_paxos/target/nodes.cfg",
						       "CLIENT_COUNT":"5",
						       "CLIENT_SLEEP_TIME":"1",
						       "CLIENT_IP":"127.0.0.1",
						       "CLIENT_PORT":"9000",
						       "CLIENT_REPEAT":"9",
						       "EVALUATION":""})
		ret = newConfig.read(config_file)
	except ConfigParser.MissingSectionHeaderError as e:
		logging.error(str(e))
	except ConfigParser.ParsingError as e:
		logging.error(str(e))
	except ConfigParser.Error as e:
		logging.critical("strange error? " + str(e))
	else:
		if ret:	
			return newConfig

def getGitInfo():
    import commands
    git_show = 'cd '+MSMR_ROOT+' && git show '
    githash = commands.getoutput(git_show+'| head -1 | sed -e "s/commit //"')
    git_diff = 'cd '+MSMR_ROOT+' && git diff --quiet'
    diff = commands.getoutput('cd ' +MSMR_ROOT+ ' && git diff')
    if diff:
        gitstatus = '_dirty'
    else:
        gitstatus = ''
    commit_date = commands.getoutput( git_show+
            '| head -4 | grep "Date:" | sed -e "s/Date:[ \t]*//"' )
    date_tz  = re.compile(r'^.* ([+-]\d\d\d\d)$').match(commit_date).group(1)
    date_fmt = ('%%a %%b %%d %%H:%%M:%%S %%Y %s') % date_tz
    import datetime
    gitcommitdate = str(datetime.datetime.strptime(commit_date, date_fmt))
    logging.debug( "git 6 digits hash code: " + githash[0:6] )
    logging.debug( "git reposotory status: " + gitstatus)
    logging.debug( "git commit date: " + gitcommitdate)
    return [githash[0:6], gitstatus, gitcommitdate, diff]

#make directory
def mkdir_p(path):
	try:
		os.makedirs(path)
	except OSError as exc: 
		if exc.errno == errno.EEXIST and os.path.isdir(path):
			logging.warning("%s already exists" % path)
			pass
		else: raise

def genRunDir(config_file, git_info):
	dir_name = ""
	from os.path import basename
	config_name = os.path.splitext(basename(config_file))[0]
	from time import strftime
	dir_name += config_name + strftime("%Y%b%d_%H%M%S") + '_' + git_info[0] +git_info[1]
	mkdir_p(dir_name)
	logging.debug("creating %s" % dir_name)
	return os.path.abspath(dir_name)

def extract_apps_exec(config, bench, apps_dir=""):
	bench = bench.partition('"')[0].partition("'")[0]
	apps = bench.split()
	if apps.__len__() < 1:
		raise Exception("cannot parse executible file name")
	elif apps.__len__() == 1:
		return apps[0], os.path.abspath(apps_dir + '/eval/current/' +apps[0])
	else:
		return apps[0], os.path.abspath(apps_dir + '/eval/current/' +apps[0]+'_'+apps[1]+'/'+config.get(bench,"TEST_NAME"))

def generate_local_options(config, bench):
	config_options = config.options(bench)
	output = ""
	for option in default_options:
		if option in config_options:
			entry = option + '=' + config.get(bench, option)
		else:
			entry = option + '=' + default_options[option]
		output += '%s\n' % entry
	with open("local.options", "w") as option_file:
		option_file.write(output)

def checkExist(file, flags=os.X_OK):
	if not os.path.exists(file) or not os.path.isfile(file) or not os.access(file, flags):
		return False
	return True

def copy_file(src, dst):
	import shutil
	shutil.copy(src, dst)

def which(name, flags=os.X_OK):
	result = []
	path = os.environ.get('PATH', None)
	if path is None:
		return []
	for p in os.environ.get('PATH', '').split(os.pathsep):
		p = os.path.join(p, name)
		if os.access(p, flags):
			result.append(p)
	return result

def write_stats(time1, time2, repeats, first, last, lengths):
	try:
		import numpy
	except ImportError:
		logging.error("please install 'numpy' module")
	time1_avg = numpy.average(time1)
	time1_std = numpy.std(time1)
	time2_avg = numpy.average(time2)
	time2_std = numpy.std(time2)
	length_avg = numpy.average(lengths)
	length_std = numpy.std(lengths)
	import math
	with open("stats.txt", "w") as stats:
		stats.write('Concensus Time:\n')
		stats.write('\tmean:{0} us\n'.format(time1_avg))
		stats.write('\tstd:{0}\n'.format(time1_std))
		stats.write('Response Time:\n')
		stats.write('\tmean:{0} us\n'.format(time2_avg))
		stats.write('\tstd:{0}\n'.format(time2_std))
		stats.write('Throughput:\n')
		stats.write('\t{0} req/s\n'.format(len(time1)/(last-first)))
		stats.write('Queue Length:\n')
		stats.write('\tmean:{0}\n'.format(length_avg))
		stats.write('\tstd:{0}'.format(length_std))

def preSetting(config, bench, apps_name):
	with open(config.get(bench,'TEST_NAME'), "w") as testscript:
		testscript.write('#! /bin/bash\n'+
	'TEST_NAME='+config.get(bench,'TEST_NAME')+'\n'+
	'NO=${1}\n'+
	'CUR_DIR=$MSMR_ROOT/libevent_paxos\n'+
	'LOG_SUFFIX='+config.get(bench,'LOG_SUFFIX')+'\n'+
	'SLEEP_TIME='+config.get(bench,'SLEEP_TIME')+'\n'+
	'SECONDARIES_SIZE='+config.get(bench,'SECONDARIES_SIZE')+'\n'+
	'if [ ! -e ${CUR_DIR}/${TEST_NAME} ];then\n'+
	'\tFILEPATH=${CUR_DIR}/test\n'+
	'else\n'+
	'\tFILEPATH=${CUR_DIR}\n'+
	'fi\n'+
	'if [ ! -d ${FILEPATH}/log ];then\n'+
	'\tmkdir ${FILEPATH}/log\n'+
	'fi\n'+
	'exec 2>${FILEPATH}/log/${TEST_NAME}_err_${NO}\n'+
	'export LD_LIBRARY_PATH=${FILEPATH}/../.local/lib\n'+
	'SERVER_PROGRAM=${FILEPATH}/../target/server.out\n'+
	'CONFIG_FILE='+config.get(bench,'SERVER_CONFIG')+'\n'+
	'rm -rf ${FILEPATH}/.db\n'+
	'${SERVER_PROGRAM} -n 0 -m s -c ${CONFIG_FILE} 1>${FILEPATH}/log/${TEST_NAME}_0_${NO}${LOG_SUFFIX} 2>${FILEPATH}/log/${TEST_NAME}_extra_0_${NO} &\n'+
	'PRIMARY_PID=$!\n'+
	'sleep ${SLEEP_TIME}\n'+
	'for i in $(seq ${SECONDARIES_SIZE});do\n'+
	'\t${SERVER_PROGRAM} -n ${i} -m r -c ${CONFIG_FILE} 1>${FILEPATH}/log/${TEST_NAME}_${i}_${NO}${LOG_SUFFIX} 2>${FILEPATH}/log/${TEST_NAME}_extra_${i}_${NO} &\n'+
	'declare NODE_${i}=$!\n'+
	'done\n'+
	'sleep ${SLEEP_TIME}\n'+
	'CLIENT_PROGRAM=${FILEPATH}/../client/client.out\n')
		for i in range(1,int(config.get(bench,'CLIENT_COUNT'))):
			testscript.write('${CLIENT_PROGRAM} -n '+str(i)+' -s '+config.get(bench,'CLIENT_IP')+' -p '+config.get(bench,'CLIENT_PORT')+' -r '+config.get(bench,'CLIENT_REPEAT')+' -i '+config.get(bench,'CLIENT_SLEEP_TIME')+' &>/dev/null &\n')
		testscript.write('sleep ${SLEEP_TIME}\n'+
	'kill -15 ${PRIMARY_PID} &>/dev/null\n'+
	'for i in $(echo ${!NODE*});do\n'+
	'\tkill -15 ${!i} &>/dev/null\n'+
	'done\n'+
	'LOG_NAME_0=${FILEPATH}/log/${TEST_NAME}_0_${NO}${LOG_SUFFIX}\n'+
	'LOG_NAME_0_EXTRA=${FILEPATH}/log/${TEST_NAME}_extra_0_${NO}\n'+
	'$(cp ${LOG_NAME_0} $MSMR_ROOT/eval/current/)'+
	'$(cp ${LOG_NAME_0_EXTRA} $MSMR_ROOT/eval/current/)')
	os.system('chmod +x '+config.get(bench,'TEST_NAME'))
	return

def execBench(cmd, repeats, out_dir,
	      client_cmd="", client_terminate_server=False,
	      init_env_cmd=""):
	mkdir_p(out_dir)
	for i in range(int(repeats)):
		sys.stderr.write("        PROGRESS: %5d/%d\r" % (i+1, int(repeats)))
		with open('%s/output.%d' % (out_dir, i), 'w', 102400) as log_file:
			if init_env_cmd:
				os.system(init_env_cmd)
			proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, shell=True, executable=bash_path, bufsize=102400)
			if client_cmd:
				time.sleep(1)
				with open('%s/client.%d' % (out_dir, i), 'w', 102400) as client_log_file:
					client_proc = subprocess.Popen(client_cmd, stdout=client_log_file, stderr=subprocess.STDOUT, shell=True, executable=bash_path, bufsize=102400)
					client_proc.wait()
				if client_terminate_server:
					os.killpg(proc.pid, signal.SIGTERM)
				proc.wait()
				time.sleep(2)
			else:
				try:
					proc.wait()
				except KeyboardInterrupt as k:
					try:
						os.killpg(proc.pid, signal.SIGTERM)
					except:
						pass
					raise k
		try:
			os.renames('out', '%s/out.%d' % (out_dir, i))
		except OSError:
			pass

def processBench(config, bench):
		
	logging.debug("processing: " + bench)
	specified_evaluation = config.get(bench, 'EVALUATION')
	apps_name, exec_file = extract_apps_exec(config, bench, APPS)
	logging.debug("app = %s" % apps_name)
	logging.debug("executible file = %s" % exec_file)
	
	segs = re.sub(r'(\")|(\.)|/|\'', '', bench).split()
	dir_name = ""
	dir_name += '_'.join(segs)
	mkdir_p(dir_name)
	os.chdir(dir_name)
	
	generate_local_options(config, bench)
	inputs = config.get(bench, 'inputs')
	repeats = config.get(bench, 'repeats')
	
	if specified_evaluation:
		specified = __import__(specified_evaluation, globals(), locals(), [], -1)
		specified.evaluation(int(repeats))
		return
	
	preSetting(config, bench, apps_name)
	
	export = config.get(bench, 'EXPORT')
	if export:
		logging.debug("export %s", export)

	# generate command for MSMR [time LD_PRELOAD=... exec args...]
	msmr_command = ' '.join([export, exec_file] + inputs.split())
	logging.info("executing '%s'" % msmr_command)
	execBench(msmr_command, repeats, 'msmr')
		
	# get stats
	time1 = []
	time2 = []
	lengths = []
	for i in range(int(repeats)):
		log_file_name = MSMR_ROOT+'/eval/current/'+config.get(bench,'TEST_NAME')+'_0_'+inputs.split()[0]+config.get(bench,'LOG_SUFFIX')
		print log_file_name
		lines = (open(log_file_name, 'r').readlines())
		first = float(lines[1].split(',')[0])
		for line in lines:
			if ',' in line and 'connect' not in line and 'send' not in line and 'receive' not in line and 'close' not in line:
				time1 += [(-float(line.split(',')[1])+float(line.split(',')[2]))*1000000]
				time2 += [(-float(line.split(',')[0])+float(line.split(',')[3]))*1000000]
				last = float(line.split(',')[3])
		log_file_name = MSMR_ROOT+'/eval/current/'+config.get(bench,'TEST_NAME')+'_extra_0_'+inputs.split()[0]
		print log_file_name
		lines = (open(log_file_name, 'r').readlines())
		for line in lines:
			if 'the length' in line:
				lengths += [float(line.split(' ')[-1])]
	#print time3
	#print time4
	#print lengths
	write_stats(time1, time2, int(repeats), first, last, lengths)
	# copy exec file
	#copy_file(os.path.realpath(exec_file), os.path.basename(exec_file))
	
def workers(semaphore, lock, configs, bench):
	from multiprocessing import Process
	with semaphore:
		p = Process(target=processBench, args=(configs, bench))
		with lock:
			logging.debug("STARTING %s" % bench)
			p.start()
		p.join()
		with lock:
			logging.debug("FINISH %s" % bench)

if __name__ == "__main__":
	logger = logging.getLogger()
	formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s","%Y%b%d-%H:%M:%S")
	ch = logging.StreamHandler()
	ch.setFormatter(formatter)
	ch.setLevel(logging.DEBUG)
	logger.addHandler(ch)
	logger.setLevel(logging.DEBUG)

	try:
		MSMR_ROOT = os.environ["MSMR_ROOT"]
		logging.debug('MSMR_ROOT = ' + MSMR_ROOT)
	except KeyError as e:
		logging.error("Please set the environment variable " + str(e))
		sys.exit(1)

	APPS = os.path.abspath(MSMR_ROOT+"/")
	# parse input arguments
	parser = argparse.ArgumentParser(
		description = "Evaluate the performance of MSMR")
	parser.add_argument('filename', nargs='*',
		type=str,
		default = ["msmr.cfg"],
		help = "list of configuration files (default: msmr.cfg)")
	args = parser.parse_args()

	if args.filename.__len__() == 0:
		logging.critical(' no configuration file specified??')
		sys.exit(1)
	elif args.filename.__len__() == 1:
		logging.debug('config file: ' + ''.join(args.filename))
	else:
		logging.debug('config files: ' + ', '.join(args.filename))

	logging.debug("set timeformat to '\\nreal %E\\nuser %U\\nsys %S'")
	os.environ['TIMEFORMAT'] = "\nreal %E\nuser %U\nsys %S"

	# run command in shell
	bash_path = which('bash')
	if not bash_path:
		logging.critical("cannot find shell 'bash'")
		sys.exit(1)
	else:
		bash_path = bash_path[0]
		logging.debug("find 'bash' at %s" % bash_path)

	default_options = getMsmrDefaultOptions()
	git_info = getGitInfo()
	root_dir = os.getcwd()
	
	for config_file in args.filename:
		logging.info("processing '" + config_file + "'")
		full_path = getConfigFullPath(config_file)
		
		local_config = readConfigFile(full_path)
		if not local_config:
			logging.warning("skip " + full_path)
			continue
		
		run_dir = genRunDir(full_path, git_info)
		try:
			os.unlink('current')
		except OSError:
			pass
		os.symlink(run_dir, 'current')
		if not run_dir:
			continue
		os.chdir(run_dir)
		if git_info[3]:
			with open("git_diff", "w") as diff:
				diff.write(git_info[3])

		benchmarks = local_config.sections()
		all_threads = []
		semaphore = threading.BoundedSemaphore(1)
		log_lock = threading.Lock()
		for benchmark in benchmarks:
			if benchmark == "default" or benchmark == "example":
				continue
			processBench(local_config, benchmark)

		os.chdir(root_dir)
