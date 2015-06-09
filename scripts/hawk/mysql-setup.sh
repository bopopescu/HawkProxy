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

LOG_INFO "Setup mysql database" 


    
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
    
$curdir/config-mysql.sh
 
service mysql restart 
sleep 1   
    

CMD="$MYSQL -u$mysql_cloudflowDB_user -p$mysql_cloudflowDB_password -h$cfd_Internal_VIP -Bse"
SQLFILE="$MYSQL -u$mysql_root_user -p$mysql_root_password -h$cfd_Internal_VIP -Bs"
SQL_INIT_CMD="$MYSQL -u$mysql_cloudflowDB_user -p$mysql_cloudflowDB_password"  
    
sudo mysqladmin -u$mysql_root_user -p$mysql_root_password flush-hosts
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "grant all privileges on *.* to $mysql_root_user @'%';"
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "set password for $mysql_root_user @'%'=PASSWORD('$mysql_root_password');"
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "grant all privileges on *.* to $mysql_root_user @'%';"        
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "UPDATE mysql.user set  grant_priv='y' where user='$mysql_root_user '"
#
#   CloudFlow Database      
#       
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "DROP database if exists $mysql_cloudflowDB_name;"
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "CREATE DATABASE $mysql_cloudflowDB_name;"



sudo mysql -u$mysql_root_user -p$mysql_root_password -e "GRANT USAGE ON *.* TO $mysql_cloudflowDB_user;"    # done simply to create if one does not exist
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "DROP USER $mysql_cloudflowDB_user;"                # now it can be droped without an error
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "CREATE USER $mysql_cloudflowDB_user;"
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "GRANT ALL PRIVILEGES ON $mysql_cloudflowDB_name.* TO '$mysql_cloudflowDB_user'@'%';"
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "SET PASSWORD FOR '$mysql_cloudflowDB_user'@'%' = PASSWORD ('$mysql_cloudflowDB_password') ;"
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "GRANT ALL PRIVILEGES ON $mysql_cloudflowDB_name.* TO '$mysql_cloudflowDB_user'@'localhost';"
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "SET PASSWORD FOR '$mysql_cloudflowDB_user'@'localhost' = PASSWORD ('$mysql_cloudflowDB_password') ;"


sudo mysql -u$mysql_root_user -p$mysql_root_password -e "GRANT USAGE ON *.* TO $mysql_php_user;"    # done simply to create if one does not exist
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "DROP USER $mysql_php_user;"                # now it can be droped without an error
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "CREATE USER $mysql_php_user;"
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "GRANT SELECT, SHOW VIEW ON $mysql_cloudflowDB_name.* TO '$mysql_php_user'@'%';"
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "SET PASSWORD FOR '$mysql_php_user'@'%' = PASSWORD ('$mysql_php_password') ;"
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "GRANT SELECT, SHOW VIEW  ON $mysql_cloudflowDB_name.* TO '$mysql_php_user'@'localhost';"
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "SET PASSWORD FOR '$mysql_php_user'@'localhost' = PASSWORD ('$mysql_php_password') ;"

sudo mysql -u$mysql_root_user -p$mysql_root_password -e "SET GLOBAL time_zone = '+00:00';"
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "SET GLOBAL max_connections = 512;"
sudo mysql -u$mysql_root_user -p$mysql_root_password -e "SET GLOBAL connect_timeout = 12;"

sudo mysql -u$mysql_root_user -p$mysql_root_password -e "FLUSH PRIVILEGES ;"







sudo mysql -u$mysql_root_user -p$mysql_root_password -e "SET GLOBAL connect_timeout = 12 ;"


if [ -f $curdir/../../../db-models/CloudFlowPortal.sql ] ; then
    cp $curdir/../../../db-models/CloudFlowPortal.sql $curdir/CloudFlowPortal.sql
fi
$SQLFILE < $curdir/CloudFlowPortal.sql
LOG_INFO "Setup mysql database completed" 
