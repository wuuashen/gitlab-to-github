#!/bin/bash

echo "🚀 GitLab 到 GitHub 迁移工具 - 快速设置"
echo "=" * 50

# 检查 Python
echo "1. 检查 Python..."
if command -v python3 &> /dev/null; then
    echo "✅ Python3 已安装: $(python3 --version)"
else
    echo "❌ Python3 未安装，请先安装 Python3"
    exit 1
fi

# 检查 Python 依赖
echo "2. 检查 Python 依赖..."
python3 -c "import requests, dotenv" 2>/dev/null && echo "✅ 依赖已安装" || {
    echo "📦 安装 Python 依赖（requests, python-dotenv）..."
    if [ -f requirements.txt ]; then
        pip3 install -r requirements.txt
    else
        pip3 install requests python-dotenv
    fi
}

# 检查 gh CLI
echo "3. 检查 GitHub CLI..."
if command -v gh &> /dev/null; then
    echo "✅ GitHub CLI 已安装: $(gh --version | head -1)"
else
    echo "❌ GitHub CLI 未安装，请安装:"
    echo "   macOS: brew install gh"
    echo "   其他系统: https://cli.github.com/"
    exit 1
fi

# 检查 gh 登录状态
echo "4. 检查 GitHub 登录状态..."
if gh auth status &>/dev/null; then
    echo "✅ GitHub CLI 已登录"
    gh auth status
else
    echo "❌ GitHub CLI 未登录，请运行: gh auth login"
    exit 1
fi

# 检查环境变量
echo "5. 检查环境变量..."
if [ -z "$GITLAB_ACCESS_TOKEN" ]; then
    echo "⚠️  GITLAB_ACCESS_TOKEN 未设置"
    echo "   请创建 GitLab Personal Access Token 并设置:"
    echo "   export GITLAB_ACCESS_TOKEN='your_token_here'"
else
    echo "✅ GITLAB_ACCESS_TOKEN 已设置"
fi

# 检查 GitHub Actions Importer（可选）
echo "6. 检查 GitHub Actions Importer（可选）..."
if gh actions-importer --version &>/dev/null; then
    echo "✅ GitHub Actions Importer 已安装（可用于 CI 迁移）"
else
    echo "ℹ️  未安装 GitHub Actions Importer。若需要迁移 CI，请运行:"
    echo "   gh extension install github/gh-actions-importer"
fi

# （可选）检查 Actions Importer 配置
echo "7. （可选）如需迁移 CI，请运行并配置:"
echo "   gh actions-importer configure"
echo "   选择 GitLab CI 并输入对应的 token"

echo ""
echo "🎉 设置检查完成！"
echo "如果所有检查都通过，您可以运行迁移脚本:"
echo "   python3 index.py"
echo ""
echo "可选：无本地克隆模式（使用 GitHub Import API）"
echo "   export USE_GITHUB_IMPORT=1 && python3 index.py"
