#!/bin/bash
set -e;
set -u;
#set -v;
#set -x;
curdir=$(dirname $(readlink -f $0))

. $curdir/../common/bashLogManager.sh

$curdir/../hawk/config-mysql.sh


STOP_SERVICE keystone

LOG_INFO  "Set up database" 
rm  -f /var/lib/keystone/keystone.db

cfd_Internal_VIP="127.0.0.1"
mysql_root_user="root"
mysql_root_password="cloud2674"

mysql_keystoneDB_name="keystone"
mysql_keystoneDB_user="keystone_admin"
mysql_keystoneDB_password="cloud"

touch $logdir/keystone.log
chown keystone:keystone $logdir/keystone.log

sudo mysql -h $cfd_Internal_VIP -u$mysql_root_user -p$mysql_root_password -e "drop database if exists $mysql_keystoneDB_name;"
sudo mysql -h $cfd_Internal_VIP -u$mysql_root_user -p$mysql_root_password  -e "CREATE DATABASE $mysql_keystoneDB_name;"

sudo mysql -h $cfd_Internal_VIP -u$mysql_root_user -p$mysql_root_password  -e "GRANT USAGE ON *.* TO $mysql_keystoneDB_user;"  # done simply to create if one does not exist
sudo mysql -h $cfd_Internal_VIP -u$mysql_root_user -p$mysql_root_password  -e "DROP USER $mysql_keystoneDB_user;"              # now it can be droped without an error

sudo mysql -h $cfd_Internal_VIP -u$mysql_root_user -p$mysql_root_password  -e "CREATE USER $mysql_keystoneDB_user;"
sudo mysql -h $cfd_Internal_VIP -u$mysql_root_user -p$mysql_root_password  -e "GRANT ALL PRIVILEGES ON $mysql_keystoneDB_name.* TO '$mysql_keystoneDB_user'@'%' ;"

sudo mysql -h $cfd_Internal_VIP -u$mysql_root_user -p$mysql_root_password  -e "GRANT ALL PRIVILEGES ON $mysql_keystoneDB_name.* TO '$mysql_keystoneDB_user'@localhost ;"



sudo mysql -h $cfd_Internal_VIP -u$mysql_root_user -p$mysql_root_password  -e "SET PASSWORD FOR '$mysql_keystoneDB_user'@'%' = PASSWORD ('$mysql_keystoneDB_password') ;"
sudo mysql -h $cfd_Internal_VIP -u$mysql_root_user -p$mysql_root_password  -e "SET PASSWORD FOR '$mysql_keystoneDB_user'@localhost = PASSWORD ('$mysql_keystoneDB_password') ;"





LOG_INFO "Database initialized" 

sql="connection \= mysql\:\/\/$mysql_keystoneDB_user\:$mysql_keystoneDB_password\@$cfd_Internal_VIP\/$mysql_keystoneDB_name"
#echo $sql
bindhost="bind_host = $cfd_Internal_VIP"

cp -r -p $curdir/keystone_etc/* /etc/keystone

## fix up keystone.CONF

line=$(grep -i -n -m 1 "connection = sqlite:////var/lib/keystone/keystone.db" /etc/keystone/keystone.conf | awk -F: '{print $1}')
LOG_INFO "connection line number is $line"
sed -i -e ${line}s/.*/"$sql"/   /etc/keystone/keystone.conf
LOG_INFO $(grep -i -n -m 1 "connection =" /etc/keystone/keystone.conf)

line=$(grep -i -n -m 1 "bind_host =" /etc/keystone/keystone.conf | awk -F: '{print $1}')
sed -i -e ${line}s/.*/"$bindhost"/   /etc/keystone/keystone.conf
LOG_INFO $(grep -i -n -m 1 "bind_host =" /etc/keystone/keystone.conf)


#debugoption="debug = True"
#line=$(grep -i -n -m 1 "debug =" /etc/keystone/keystone.conf | awk -F: '{print $1}')
#sed -i -e ${line}s/.*/"$debugoption"/   /etc/keystone/keystone.conf
#LOG_INFO $(grep -i -n -m 1 "debug =" /etc/keystone/keystone.conf)


verboseoption="verbose = True"
line=$(grep -i -n -m 1 "verbose =" /etc/keystone/keystone.conf | awk -F: '{print $1}')
sed -i -e ${line}s:.*:"$verboseoption":   /etc/keystone/keystone.conf
LOG_INFO  $(grep -i -n -m 1 "verbose =" /etc/keystone/keystone.conf)

#
OIFS=$IFS
IFS='.'
logoption="log_dir = $logdir"
line=$(grep -i -n -m 1 "log_dir =" /etc/keystone/keystone.conf | awk -F: '{print $1}')
echo $line
sed -i -e ${line}s:.*:$logoption:   /etc/keystone/keystone.conf
IFS=$OIFS
LOG_INFO $(grep log_dir /etc/keystone/keystone.conf)


LOG_INFO "Config file initialized"

RESTART_SERVICE keystone
sleep 1
#
#   WAIT FOR KEYSTONE SERVICE TO BECOME ACTIVE 
#
        while :
        do
	    LOG_INFO "Waiting for keystone to finish initialization"

            keystone --version
            if [ $? -eq 0 ] ; then
                break ;
            fi
            sleep 1
        done
            
LOG_INFO "Resync Keystone service DB"
keystone-manage db_sync  >/dev/null 2>&1
sleep 5
curl -X GET -H "X-Auth-token:ADMIN" -H "Content-Type: application/json"  http://localhost:35357/v3/domains
