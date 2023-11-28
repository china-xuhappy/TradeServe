#!/bin/bash

# 定义你的Python项目的启动命令和相关信息
project_dir="/home/xuhappy/xuhappy/HappyKData"
rd_main_script="/remind/rd_main.py"


# 检查是否已经有相同的Python项目在运行
if pgrep -f "python3 $project_dir/$rd_main_script" > /dev/null; then
    echo "发现rd_main_script 已经运行的Python项目，正在关闭..."
    pkill -f "python3 $project_dir/$rd_main_script"
    sleep 2
fi

# 启动Python项目
sleep 2

echo "启动Python项目..."
nohup python3 "$project_dir/$rd_main_script" > "$project_dir/rd_main_script.log" 2>&1 &

# 打印提示信息
echo "Python项目已启动。"
