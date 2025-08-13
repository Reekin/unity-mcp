#!/usr/bin/env python3
"""
Unity编译独立CLI工具
可以被PowerShell脚本直接调用，无需启动MCP服务器
支持并行运行，不与现有MCP服务器冲突
"""

import sys
import json
import logging
import argparse
from typing import Optional
from unity_compile_core import UnityCompileCore
from config import config

def setup_logging(verbose: bool = False):
    """Setup logging configuration, unified recording to unity_mcp_server.log"""
    log_level = logging.DEBUG if verbose else logging.INFO
    
    # Configure log format and file output, consistent with unity_connection.py
    logging.basicConfig(
        level=log_level,
        format=config.log_format,
        filename='unity_mcp_server.log',
        filemode='a'
    )
    
    # Also output to console (optional)
    if verbose:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(logging.Formatter(config.log_format))
        logging.getLogger().addHandler(console_handler)

def main():
    """Command line main entry"""
    parser = argparse.ArgumentParser(description="Unity standalone compilation tool")
    parser.add_argument("--no-trigger", action="store_true", 
                       help="Don't trigger Unity compilation, only read existing logs")
    parser.add_argument("--output", choices=["json", "text"], default="text",
                       help="Output format (default: text)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Verbose output and logging")
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.verbose)
    logger = logging.getLogger("unity-mcp-server")
    
    try:
        logger.info("Starting Unity standalone compilation")
        
        # Execute compilation
        result = UnityCompileCore.compile_project(
            unity_connection=None,  # Let core module create connection itself
            skip_trigger=args.no_trigger
        )
        
        # Output results
        if args.output == "json":
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            # Text format output with ASCII compatible symbols
            if result["success"]:
                print(f"{result['message']}")
                if result["compilation_logs"]:
                    print(f"\n[LOGS] Compilation logs ({len(result['compilation_logs'])} entries):")
                    for i, log in enumerate(result["compilation_logs"], 1):
                        print(f"  {i:3d}. {log}")
                else:
                    print("[LOGS] No compilation errors or warnings")
            else:
                print(f"[COMPILATION FAILED] {result['message']}")
        
        logger.info(f"Compilation completed, success: {result['success']}")
        
        # Return appropriate exit code
        sys.exit(0 if result["success"] else 1)
        
    except KeyboardInterrupt:
        print("\n[INTERRUPT] User interrupted")
        logger.info("User interrupted compilation process")
        sys.exit(130)
    except Exception as e:
        error_msg = f"Execution failed: {str(e)}"
        print(f"[ERROR] {error_msg}")
        logger.error(error_msg)
        sys.exit(1)

if __name__ == "__main__":
    main()