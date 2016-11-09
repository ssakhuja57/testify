#!/bin/bash

port=$1
log_dir="logs"
log="$log_dir/testify-$(date +%Y%m%d-%H%M%S).log"

mkdir -p $log_dir
nohup python -u testifyui.py $port > $log 2>&1 &
