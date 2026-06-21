#!/bin/bash
# 清理的测试运行脚本 - 抑制zsh警告

# 抑制zsh的compinit警告
export ZSH_DISABLE_COMPFIX=true

# 运行测试并只显示重要信息
python3 -m pytest "$@" 2>&1 | grep -v "not interactive" | grep -v "compinit" | grep -v "complete:13"

# 返回pytest的退出码
exit ${PIPESTATUS[0]}
