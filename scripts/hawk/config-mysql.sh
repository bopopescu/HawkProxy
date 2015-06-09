
#!/bin/bash
set -u ; set -e
set -x ; set -v


if [ ! -f /etc/mysql/my.cnf ] ; then
    echo "Exit mysql configuration file not present." 
    exit 2
fi   
    
bindaddress=$(grep -m 1 bind-address /etc/mysql/my.cnf | awk ' {print $3 }')
if [ "$bindaddress" != "0.0.0.0" ] ; then
	line=$(grep -i -n -m 1 bind-address /etc/mysql/my.cnf | awk -F: '{print $1}')
	sed -i "${line}c bind-address = 0.0.0.0 " /etc/mysql/my.cnf
fi 


if ! grep "default_time_zone"  /etc/mysql/my.cnf ; then
    line=$(grep -i -n "\[mysqld\]" /etc/mysql/my.cnf | awk -F: '{print $1}')
    echo "line number is: $line"
    if [ "$line" != "" ] ; then
        sed -i "${line}a default_time_zone = \'+00:00\'" /etc/mysql/my.cnf 
    fi
fi

if ! grep "innodb_file_per_table"  /etc/mysql/my.cnf ; then
    line=$(grep -i -n "\[mysqld\]" /etc/mysql/my.cnf | awk -F: '{print $1}')
    echo "line number is: $line"
    if [ "$line" != "" ] ; then
        sed -i "${line}a innodb_file_per_table" /etc/mysql/my.cnf 
    fi
fi

line=$(grep -i -n "max_connections" /etc/mysql/my.cnf | awk -F: '{print $1}')
echo "line number is: $line"
if [ "$line" != "" ] ; then
    sed -i "${line}s:.*:max_connections = 512:" /etc/mysql/my.cnf 
fi
