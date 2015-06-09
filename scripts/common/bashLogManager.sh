#!/bin/bash


if set -o | grep verbose | grep -q on ; then setv=true ; else setv=false ; fi ; set +v
if set -o | grep xtrace | grep -q on ; then setx=true ; else setx=false ; fi ; set +x
set -u ; set -e
#cmdlog=cfacmd.log
#exec >> /root/cfa-config/$cmdlog 2>&1
#set -x ; set -v
#HISTTIMEFORMAT='%F %T '
#set -o history -o histexpand

pidid="$$"  
curdir=$(dirname $(readlink -f $0))
project_rootdir="hawk"

pgm_name=`basename $0`

pgt_rootdir=$(readlink -f $curdir/../)
while :
do
    dn=`basename $pgt_rootdir` 
    if [ "$dn" = "$project_rootdir" ] ; then
        break ;
    fi  
    if [ "$dn" = "/" ] ; then
        echo "Unable to locate project root directory = $project_rootdir directory - exit"
        exit 2
    fi  
    pgt_rootdir=$(readlink -f $pgt_rootdir/../) 
done
echo "Project root directory $project_rootdir is at $pgt_rootdir"
sys_rootdir=$(readlink -f $pgt_rootdir/../)



#logdir="$sys_rootdir/var/$project_rootdir/log"
logdir="/var/log/cloudflow"
mkdir -p $logdir

piddir="/var/run/cloudflow"
mkdir -p $piddir


logfile=$logdir/$pgm_name.log

fn=`basename $0` 
myname=`hostname`

set +u



if set -o | grep nounset | grep -q on ; then setu=true ; else setu=false ; fi  ; set +u
. $curdir/../common/bashtasklog.sh
if [ ! -z $logfile ] ; then
        new bashtasklog logger -f -w 80 -l $logfile
else
        new bashtasklog logger -f -w 80 -l
        CURR_DEB_LOG=/dev/null
fi
if [ "$setu" = true ] ; then  set -u ; else set -u ; fi 


LOG_INFO()
{
    if set -o | grep verbose | grep -q on ; then setv=true ; else setv=false ; fi ; set +v
    if set -o | grep xtrace | grep -q on ; then setx=true ; else setx=false ; fi ; set +x
    if set -o | grep nounset | grep -q on ; then setu=true ; else setu=false ; fi ; set +u
    logger.printTask " [$myname] [$pidid] $fn $@  "
    logger.printOk
    if [ "$setu" = true ] ; then  set -u ; else set +u ; fi 
    if [ "$setv" = true ] ; then  set -v ; else set +v ; fi 
    if [ "$setx" = true ] ; then  set -x ; else set +x ; fi 
}

LOG_INFO_QUIET()
{
    if set -o | grep verbose | grep -q on ; then setv=true ; else setv=false ; fi ; set +v
    if set -o | grep xtrace | grep -q on ; then setx=true ; else setx=false ; fi ; set +x
    if set -o | grep nounset | grep -q on ; then setu=true ; else setu=false ; fi ; set +u
    logger.printTaskQuiet " [$myname] [$pidid] $fn $@  " 
    logger.printOkQuiet
    if [ "$setu" = true ] ; then  set -u ; else set +u ; fi 
    if [ "$setv" = true ] ; then  set -v ; else set +v ; fi 
    if [ "$setx" = true ] ; then  set -x ; else set +x ; fi 
}


LOG_ERROR()
{
    if set -o | grep verbose | grep -q on ; then setv=true ; else setv=false ; fi ; set +v
    if set -o | grep xtrace | grep -q on ; then setx=true ; else setx=false ; fi ; set +x
    if set -o | grep nounset | grep -q on ; then setu=true ; else setu=false ; fi ; set +u
    logger.printTask " [$myname] [$pidid] $fn $@  "
    logger.printFail
    if [ "$setu" = true ] ; then  set -u ; else set +u ; fi 
    if [ "$setv" = true ] ; then  set -v ; else set +v ; fi 
    if [ "$setx" = true ] ; then  set -x ; else set +x ; fi  
}
LOG_WARN()
{
    if set -o | grep nounset | grep -q on ; then setu=true ; else setu=false ; fi 
    set +u
    logger.printTask " [$myname] [$pidid] $fn $@  "
    logger.printWarn
    if [ "$setu" = true ] ; then  set -u ; else set -u ; fi 
}
LOG_ERROR_FILE()
{
    if set -o | grep nounset | grep -q on ; then setu=true ; else setu=false ; fi 
    set +u
    logger.printTask " [$myname] [$pidid] $fn $@  "
    logger.printWarn
    if [ "$setu" = true ] ; then  set -u ; else set -u ; fi 
}

RUN_LOG_BASH_JOB()
{
    if set -o | grep errexit | grep -q on ; then sete=true ; else sete=false ; fi ; set +e
    args=$(echo "$*")
    cmd=$1
    LOG_INFO "Starting $args "
    $@  2>$cloudflow_temp_dir/$pidid-errors
    if [ $? != 0 ] ; then
        lastStatus=$?
        errorFile=$(cat $cloudflow_temp_dir/$pidid-errors)
        rm $cloudflow_temp_dir/$pidid-errors
        LOG_ERROR "$$args exit status is $lastStatus as:$errorFile" 
        if [ "$sete" = true ] ; then  set -e ; else set +e ; fi
        exit $lastStatus
    fi  
    LOG_INFO "DONE $args"
    if [ "$sete" = true ] ; then  set -e ; else set +e ; fi  
}

LOG_CHECKING()
{
    if set -o | grep nounset | grep -q on ; then setu=true ; else setu=false ; fi 
    set +u
    logger.printTask " [$myname] [$pidid] $fn $@  "
    if [ "$setu" = true ] ; then  set -u ; else set -u ; fi 
}
LOG_CHECK_OK()
{
    if set -o | grep nounset | grep -q on ; then setu=true ; else setu=false ; fi 
    set +u
    logger.printOk
    if [ "$setu" = true ] ; then  set -u ; else set -u ; fi 
}
LOG_CHECK_FAIL()
{
    if set -o | grep nounset | grep -q on ; then setu=true ; else setu=false ; fi 
    set +u
    logger.printFail
    if [ "$setu" = true ] ; then  set -u ; else set -u ; fi 
}

LOG_CHECK_WARN()
{
    if set -o | grep nounset | grep -q on ; then setu=true ; else setu=false ; fi 
    set +u
    logger.printWarn
    if [ "$setu" = true ] ; then  set -u ; else set -u ; fi 
}



















STOP_SERVICE()
{
 LOG_INFO "Stop: service $1"
 if service $1 status | grep running &>/dev/null ; then
    LOG_INFO "Stopping service $1"
    service $1 stop &>/dev/null
 else
    LOG_INFO "Service $1 already stopped"
    return
 fi
 
# ensure that it is done 
 if service $1 status | grep running &>/dev/null ; then
    LOG_INFO "Pausing 1 second for $1 to stop"
    sleep 1 &>/dev/null
 fi
}

START_SERVICE()
{
 if service $1 status | grep running &>/dev/null ; then
    LOG_INFO "Service $1 is already running"
    return
 fi   
 service $1 start &>/dev/null 
}

RESTART_SERVICE()
{
    STOP_SERVICE $1
    START_SERVICE $1
}

if [ "$setv" = true ] ; then  set -v ; else set +v ; fi 
if [ "$setx" = true ] ; then  set -x ; else set +x ; fi
