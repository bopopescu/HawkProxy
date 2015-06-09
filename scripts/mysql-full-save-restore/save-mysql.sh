#!/bin/bash
set -u ; set -e
#cmdlog=cfdcmd.log
#exec >> /root/cfd-config/$cmdlog 2>&1
set -x ; set -v  

curdir=$(dirname $(readlink -f $0)) 
myname=`hostname`
pidid="$$"  
fn=`basename $0` 
dir=$(pwd)    

. $curdir/../common/bashLogManager.sh


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
  
 
db_name=$(date| sed -e 's/ /-/g' | sed -e 's/:/-/g')

mysqldump -u$mysql_root_user -p$mysql_root_password --single-transaction --all-databases   | gzip -9 > $curdir/portal-$db_name.sql.gz

