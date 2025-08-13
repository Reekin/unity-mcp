"""
Unity编译核心模块
提供可被MCP服务器和独立脚本共同使用的编译逻辑
"""

import os
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from config import config

logger = logging.getLogger("unity-mcp-server")

class UnityCompileCore:
    """Unity编译核心逻辑，不依赖MCP框架"""
    
    @staticmethod
    def trigger_compilation_via_unity(unity_connection=None) -> bool:
        """
        通过Unity连接触发编译
        
        Args:
            unity_connection: Unity连接对象，如果为None则尝试创建新连接
            
        Returns:
            bool: 是否成功触发编译
        """
        try:
            if unity_connection is None:
                from unity_connection import get_unity_connection
                unity_connection = get_unity_connection()
            
            if unity_connection:
                logger.info("Triggering Unity compilation via project_files_refresher...")
                refresh_response = unity_connection.send_command("project_files_refresher", {})
                
                # Handle different response formats
                success = refresh_response.get("success", True)
                if isinstance(refresh_response, dict) and "error" not in refresh_response:
                    success = True
                
                if success:
                    logger.info("project_files_refresher executed successfully")
                    time.sleep(3)  # Wait for compilation to start
                    return True
                else:
                    logger.warning(f"project_files_refresher failed: {refresh_response.get('error', 'Unknown error')}")
                    return False
            else:
                logger.warning("Unity connection not available, skipping compilation trigger")
                return False
                
        except Exception as e:
            logger.warning(f"Failed to trigger Unity compilation: {str(e)}")
            return False
    
    @staticmethod
    def get_editor_log_path() -> Optional[Path]:
        """Get Unity Editor.log file path"""
        localappdata = os.environ.get('LOCALAPPDATA')
        if not localappdata:
            # WSL environment, try to use Windows path
            user = os.environ.get('USER', 'Unknown')
            localappdata = f"/mnt/c/Users/{user}/AppData/Local"
        
        editor_log_path = Path(localappdata) / "Unity" / "Editor" / "Editor.log"
        
        if not editor_log_path.exists():
            logger.error(f"Unity Editor.log not found: {editor_log_path}")
            return None
            
        return editor_log_path
    
    @staticmethod
    def parse_compilation_logs(editor_log_path: Path) -> Dict[str, Any]:
        """
        Parse Unity compilation logs
        
        Args:
            editor_log_path: Editor.log file path
            
        Returns:
            Dict[str, Any]: Parsing result
        """
        try:
            with open(editor_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            # Find the last "EditorCompilation:InvokeCompilationStarted"
            compilation_start_index = -1
            for i in range(len(lines) - 1, -1, -1):
                if "EditorCompilation:InvokeCompilationStarted" in lines[i]:
                    compilation_start_index = i
                    break
            
            if compilation_start_index == -1:
                return {
                    "success": False,
                    "message": "EditorCompilation:InvokeCompilationStarted marker not found",
                    "compilation_logs": []
                }
            
            # Find the last "* Tundra" line
            tundra_index = -1
            for i in range(len(lines) - 1, compilation_start_index, -1):
                if "* Tundra" in lines[i]:
                    tundra_index = i
                    break
            
            if tundra_index == -1:
                return {
                    "success": False,
                    "message": "* Tundra not found after EditorCompilation:InvokeCompilationStarted",
                    "compilation_logs": []
                }
            
            # Find "# Output" line
            output_start_index = -1
            for i in range(tundra_index - 1, compilation_start_index, -1):
                if "# Output" in lines[i]:
                    output_start_index = i
                    break
            
            if output_start_index == -1:
                return {
                    "success": True,
                    "message": f"No errors found in this compilation. (# Output not found before * Tundra (from {compilation_start_index} to {tundra_index}))",
                    "compilation_logs": []
                }
            
            # Extract compilation logs
            compilation_logs = []
            for i in range(output_start_index + 1, tundra_index):
                line = lines[i].strip()
                if line:  # Skip empty lines
                    compilation_logs.append(line)
            
            return {
                "success": True,
                "message": f"Successfully read {len(compilation_logs)} compilation records (from {output_start_index} to {tundra_index})",
                "compilation_logs": compilation_logs
            }
            
        except Exception as e:
            logger.error(f"Error parsing compilation logs: {str(e)}")
            return {
                "success": False,
                "message": f"Error reading log: {str(e)}",
                "compilation_logs": []
            }
    
    @classmethod
    def compile_project(cls, unity_connection=None, skip_trigger: bool = False) -> Dict[str, Any]:
        """
        Execute Unity project compilation and return results
        
        Args:
            unity_connection: Unity connection object, optional
            skip_trigger: Whether to skip compilation trigger, only read logs
            
        Returns:
            Dict[str, Any]: Compilation results
        """
        try:
            # Try to trigger Unity compilation
            if not skip_trigger:
                triggered = cls.trigger_compilation_via_unity(unity_connection)
                if not triggered:
                    logger.info("Unity compilation not triggered, will read existing compilation logs")
            else:
                logger.info("Skipping compilation trigger, reading existing logs only")
            
            # Get Editor.log path
            editor_log_path = cls.get_editor_log_path()
            if not editor_log_path:
                return {
                    "success": False,
                    "message": "Unity Editor.log not found",
                    "compilation_logs": []
                }
            
            # Parse compilation logs
            result = cls.parse_compilation_logs(editor_log_path)
            
            if result["success"]:
                logger.info(f"Compilation completed: {result['message']}")
            else:
                logger.error(f"Compilation failed: {result['message']}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error during compilation process: {str(e)}")
            return {
                "success": False,
                "message": f"Compilation error: {str(e)}",
                "compilation_logs": []
            }