#!/bin/bash
set -u ; set -e
#cmdlog=cfdcmd.log
#exec >> /root/cfd-config/$cmdlog 2>&1
set -x ; set -v  


if [ $# -ne 1 ] ; then
  echo "Plesse entore database file to restore"
  exit 1
fi


database2restore=$1


curdir=$(dirname $(readlink -f $0)) 
myname=`hostname`
pidid="$$"  
fn=`basename $0` 
dir=$(pwd)    

. $curdir/../common/bashLogManager.sh

LOG_INFO "Update mysql database" 


MYSQL="$(which mysql)"
MYSQLDUMP="$(which mysqldump)"    
    
mysql_root_user="root"
mysql_root_password="cloud2674"  
mysql_cloudflowDB_name="CloudFlowPortal"
mysql_cloudflowDB_user="cloudflowadmin"
mysql_cloudflowDB_password="1754Cloud"   


mysql_php_user="cloudflowphp"
mysql_php_password="1754Cloud"


 
cfd_Internal_VIP=0.0.0.0
    

CMD="$MYSQL -u$mysql_cloudflowDB_user -p$mysql_cloudflowDB_password -h$cfd_Internal_VIP -Bse"
SQLFILE="$MYSQL -u$mysql_root_user -p$mysql_root_password -h$cfd_Internal_VIP -Bs"
SQL_INIT_CMD="$MYSQL -u$mysql_cloudflowDB_user -p$mysql_cloudflowDB_password"  
  
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "SET GLOBAL time_zone = '+00:00';"
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "SET GLOBAL max_connections = 512;"
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "SET GLOBAL connect_timeout = 12;" 

$curdir/save-mysql.sh


set +e
mysqladmin -u$mysql_root_user -p$mysql_root_password --force drop keystone
mysqladmin -u$mysql_root_user -p$mysql_root_password --force drop CloudFlowPortal
set -e

service mysql stop
rm /var/lib/mysql/ibdata1
rm /var/lib/mysql/ib_logfile*
service mysql start
