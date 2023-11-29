#!/bin/bash

project_dir="/root/xuhappy/TradeServe/trade"
ws_script="/td_main.py"


if pgrep -f "python3 $project_dir/$ws_script" > /dev/null; then
    echo "发现 ws，正在关闭..."
    pkill -f "python3 $project_dir/$ws_script"
    sleep 1
fi

# 启动Python项目
sleep 2

echo "启动Python项目..."
nohup python3 "$project_dir/$ws_script" > "$project_dir/ws_script-output.log" 2>&1 &

# 打印提示信息
echo "Python项目已启动。"