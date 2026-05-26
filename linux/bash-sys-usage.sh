#!/bin/bash

get_cpu() {
  PREV=($(grep '^cpu ' /proc/stat))
  sleep 0.5
  CUR=($(grep '^cpu ' /proc/stat))

  PREV_TOTAL=0
  CUR_TOTAL=0

  for i in "${PREV[@]:1}"; do ((PREV_TOTAL+=i)); done
  for i in "${CUR[@]:1}"; do ((CUR_TOTAL+=i)); done

  PREV_IDLE=${PREV[4]}
  CUR_IDLE=${CUR[4]}

  DIFF_TOTAL=$((CUR_TOTAL - PREV_TOTAL))
  DIFF_IDLE=$((CUR_IDLE - PREV_IDLE))

  echo $((100 * (DIFF_TOTAL - DIFF_IDLE) / DIFF_TOTAL))
}

get_mem() {
  awk '/MemTotal/ {t=$2} /MemAvailable/ {a=$2} END {printf "%.0f", (t-a)/t*100}' /proc/meminfo
}

bar() {
  local val=$1
  local max=20
  local filled=$((val * max / 100))
  printf "["
  for ((i=0;i<filled;i++)); do printf "#"; done
  for ((i=filled;i<max;i++)); do printf "."; done
  printf "]"
}

HOST=$(hostname)
CPU=$(get_cpu)
MEM=$(get_mem)

printf "%-15s CPU: %3s%% " "$HOST" "$CPU"
bar "$CPU"
printf "  MEM: %3s%% " "$MEM"
bar "$MEM"
echo
