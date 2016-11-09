#!/bin/bash

[ $# -eq 8 ] || { echo "all 4 args required" && exit 1; }

while [[ $# -gt 1 ]]
do
key="$1"

case $key in
    --host)
	    HOST="$2"
	    shift
	    ;;
    --suite)
	    SUITE="$2"
	    shift
	    ;;
    --success)
	    SUCCESS="$2"
	    shift
	    ;;
    --fail)
	   FAIL="$2"
 	   ;;
    *)
	    echo "unknown option: $2"
	    ;;
esac
shift
done


curl "localhost:8080/testify/run?host=$HOST&suite=$SUITE&email_on_success=$SUCCESS&email_on_fail=$FAIL"
