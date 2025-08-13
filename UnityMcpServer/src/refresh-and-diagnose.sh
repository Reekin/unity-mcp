#!/bin/bash
  # 从 stdin 读取 JSON 输入
  input=$(cat)
  #echo "input: $input"

  # 提取文件路径
  file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')

  if [ -z "$file_path" ] || [ "$file_path" = "null" ]; then
      exit 0
  fi

  # 检查是否传入了 isAdd 参数 (第一个命令行参数)
  is_add=${1:-false}

  # 构建 JSON 请求体，包含 is_add 参数
  json_payload=$(jq -n \
    --arg action "refresh_project" \
    --arg file_path "$file_path" \
    --argjson is_add "$is_add" \
    '{action: $action, files: [$file_path], is_add: $is_add}')
  echo "json = $json_payload"

  # 调用 refresh_project 刷新特定文件
  response=$(curl -s -X POST http://localhost:8790/bridge \
      -H "Content-Type: application/json" \
      -d "$json_payload" 2>&1)

  # 解析JSON响应并检查diagnostics信息
  success=$(echo "$response" | jq -r '.success // false')
  total_errors=$(echo "$response" | jq -r '.diagnostics.summary.totalErrors // 0')
  total_warnings=$(echo "$response" | jq -r '.diagnostics.summary.totalWarnings // 0')

  echo "Response: success=$success, errors=$total_errors, warnings=$total_warnings"

  # 如果有错误，输出详细信息并退出
  if [ "$total_errors" -gt 0 ]; then
      echo "Found $total_errors error(s) in $file_path:" >&2
      
      # 遍历所有文件的diagnostics并输出error信息
      echo "$response" | jq -r '.diagnostics.diagnostics | to_entries[] | .key as $file | .value[] | select(.severity == "error") | "\($file):\(.line):\(.column): error: \(.message)"' >&2
      exit 2
  fi

  # 如果有警告，输出详细信息但不退出（除非需要）
  if [ "$total_warnings" -gt 0 ]; then
      echo "Found $total_warnings warning(s) in $file_path:" >&2
      
      # 遍历所有文件的diagnostics并输出warning信息
      echo "$response" | jq -r '.diagnostics.diagnostics | to_entries[] | .key as $file | .value[] | select(.severity == "warning") | "\($file):\(.line):\(.column): warning: \(.message)"' >&2
      # 可以选择是否因为警告而退出，这里保持原有行为
      exit 2
  fi

  echo "exit 0, response = $response"
  # 成功，无错误
  exit 0