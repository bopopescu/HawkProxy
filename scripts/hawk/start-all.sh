#!/bin/bash
monit quit
set -u ; set -e
#cmdlog=cfacmd.log
#exec >> /root/cfa-config/$cmdlog 2>&1
#set -x ; set -v
#HISTTIMEFORMAT='%F %T '
#set -o history -o histexpand

pidid="$$"  
curdir=$(dirname $(readlink -f $0))


. $curdir/../common/bashLogManager.sh

LOG_INFO "Setup etc directory structure" 

mkdir -p /etc/cloudflow

#cloudflow_auto_flags_dir="/etc/cloudflow/auto-generated"
#cloudflow_python_root_dir="$cloudflow_auto_flags_dir/root-python"
cloudflow_python="/etc/cloudflow"



#mkdir -p $cloudflow_auto_flags_dir
#mkdir -p $cloudflow_python_root_dir

#project_python_home_dir="$pgt_rootdir" 


#echo "# vim: tabstop=4 shiftwidth=4 softtabstop=4" > $cloudflow_python_root_dir/__init__.py
#echo "#!/usr/bin/env python" > $cloudflow_python_root_dir/cloudflowGlobals.py
#echo "# vim: tabstop=4 shiftwidth=4 softtabstop=4" >>  $cloudflow_python_root_dir/cloudflowGlobals.py
#echo "project_python_home_dir = \"$project_python_home_dir\"" >>  $cloudflow_python_root_dir/cloudflowGlobals.py


sudo cp $curdir/cloudflow_python.conf $cloudflow_python

LOG_INFO "Setup etc directory structure completed" 

$curdir/../keystone/run-keystone.sh
. $curdir/mysql-setup.sh
monit reload
sleep 1
monit restart -g hawk 
sleep 1
monit
