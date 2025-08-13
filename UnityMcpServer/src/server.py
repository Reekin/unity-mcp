from mcp.server.fastmcp import FastMCP, Context, Image
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Optional
from config import config
from unity_connection import get_unity_connection, UnityConnection
import json
from datetime import datetime
import os
import re
from pathlib import Path

logger = logging.getLogger("unity-mcp-server")

# Global connection state
_unity_connection: UnityConnection = None
_discovered_tools: List[Dict[str, Any]] = []

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Handle server startup and shutdown."""
    global _unity_connection
    logger.info("Unity MCP Server starting up")
    try:
        # Use existing connection if available, otherwise create new one
        if not _unity_connection:
            _unity_connection = get_unity_connection()
            logger.info("Connected to Unity on startup")
        
    except Exception as e:
        logger.warning(f"Could not connect to Unity on startup: {str(e)}")
        _unity_connection = None
    try:
        # Yield the connection object so it can be attached to the context
        # The key 'bridge' matches how tools like read_console expect to access it (ctx.bridge)
        yield {"bridge": _unity_connection}
    finally:
        if _unity_connection:
            _unity_connection.disconnect()
            _unity_connection = None
        logger.info("Unity MCP Server shut down")

def register_dynamic_unity_tools(mcp: FastMCP, tools_metadata: List[Dict[str, Any]]):
    """Register tools dynamically based on Unity metadata using a simpler approach."""
    logger.info(f"Registering {len(tools_metadata)} tools from Unity metadata...")
    
    # Store metadata globally for prompt generation
    global _discovered_tools
    _discovered_tools = tools_metadata
    
    # Register individual tools
    for tool_meta in tools_metadata:
        try:
            command_type = tool_meta.get("CommandType") or tool_meta.get("commandType")
            description = tool_meta.get("Description") or tool_meta.get("description", "")
            parameters = tool_meta.get("Parameters") or tool_meta.get("parameters", [])
            
            if not command_type:
                logger.warning(f"Skipping tool with missing command type: {tool_meta}")
                continue
            
            # Create a wrapper function for this specific tool
            def make_tool_func(cmd_type: str, desc: str, params_info: List[Dict]):
                # Build parameter signature dynamically
                param_names = []
                param_types = {}
                param_docs = []
                
                for param in params_info:
                    param_name = param.get("Name") or param.get("name", "unknown")
                    param_type = param.get("Type") or param.get("type", "str")
                    param_desc = param.get("Description") or param.get("description", "")
                    param_required = param.get("Required", param.get("required", True))
                    
                    param_names.append(param_name)
                    
                    # Map types
                    if param_type.lower() in ["string", "str"]:
                        param_types[param_name] = str
                    elif param_type.lower() in ["integer", "int"]:
                        param_types[param_name] = int
                    elif param_type.lower() in ["boolean", "bool"]:
                        param_types[param_name] = bool
                    else:
                        param_types[param_name] = str
                    
                    param_docs.append(f"            {param_name}: {param_desc}")
                
                # Create the function body
                def tool_func(ctx: Context, **kwargs) -> Dict[str, Any]:
                    """Tool function dynamically created for Unity command."""
                    try:
                        bridge = getattr(ctx, 'bridge', None)
                        if not bridge:
                            bridge = get_unity_connection()
                        
                        if not bridge:
                            return {"success": False, "message": "Unity connection not available"}
                        
                        # Send command to Unity
                        response = bridge.send_command(cmd_type, kwargs)
                        
                        if response.get("success"):
                            return {
                                "success": True,
                                "message": response.get("message", "Operation successful"),
                                "data": response.get("data")
                            }
                        else:
                            return {
                                "success": False,
                                "message": response.get("error", "Unknown error")
                            }
                    except Exception as e:
                        return {"success": False, "message": f"Error: {str(e)}"}
                
                # Set metadata
                tool_func.__name__ = cmd_type.replace('-', '_')
                tool_func.__doc__ = f"{desc}\n\n        Args:\n" + "\n".join(param_docs) if param_docs else desc
                
                return tool_func
            
            # Create and register the tool
            tool_func = make_tool_func(command_type, description, parameters)
            # Register the tool using FastMCP's official API
            tool_name = command_type.replace('-', '_')
            mcp.add_tool(tool_func, name=tool_name, description=description)
            logger.info(f"Registered tool: {command_type}")

            
            # Debug: Save current tools in MCP registry to JSON file
            current_tools = {}
            for name, tool in mcp._tool_manager._tools.items():
                current_tools[name] = {
                    "name": tool.name,
                    "description": tool.description,
                    "function_name": tool.function.__name__ if hasattr(tool, 'function') else 'unknown'
                }
            
        except Exception as e:
            logger.error(f"Failed to register tool {command_type}: {str(e)}")
    
    logger.info(f"Successfully registered {len(tools_metadata)} Unity tools")

def create_mcp_server() -> FastMCP:
    """Create and configure the MCP server."""
    global _unity_connection, _discovered_tools
    
    # Initialize MCP server
    mcp = FastMCP(
        "unity-mcp-server",
        description="Unity Editor integration via Model Context Protocol",
        lifespan=server_lifespan
    )
    
    # Try to connect to Unity early for dynamic tool registration
    try:
        temp_connection = get_unity_connection()
        if temp_connection:
            logger.info("Early Unity connection successful, discovering and registering tools...")
            
            # Get complete tool metadata from Unity
            response = temp_connection.send_command("list_tools", {})
            if response.get("success") and response.get("data"):
                tools_data = response["data"]
                if isinstance(tools_data, dict) and "tools" in tools_data:
                    _discovered_tools = tools_data["tools"]
                    logger.info(f"Discovered {len(_discovered_tools)} Unity tools")
                    
                    # Dynamically register tools based on Unity metadata
                    register_dynamic_unity_tools(mcp, _discovered_tools)
            
            # Keep the connection for later use
            _unity_connection = temp_connection
        else:
            logger.warning("Could not connect to Unity - tools will be unavailable")
        
    except Exception as e:
        logger.warning(f"Could not perform early tool discovery: {str(e)}")
    
    return mcp

# Create the MCP server instance
mcp = create_mcp_server()

# Static Unity Tools

@mcp.tool()
def compile_project(ctx: Context) -> Dict[str, Any]:
    """Trigger Unity project compilation and read the compilation results from Editor.log.
    
    This is the most powerful and efficient method to get the latest lint infos of the project.
    
    Returns:
        Dict[str, Any]: Dictionary containing compilation records, format:
        {
            "success": bool,
            "message": str,
            "compilation_logs": List[str]
        }
    """
    try:
        # First, trigger Unity compilation by calling project_files_refresher
        bridge = getattr(ctx, 'bridge', None)
        if not bridge:
            bridge = get_unity_connection()
        
        if bridge:
            logger.info("Triggering Unity compilation via project_files_refresher...")
            refresh_response = bridge.send_command("project_files_refresher", {})
            if not refresh_response.get("success"):
                logger.warning(f"project_files_refresher failed: {refresh_response.get('error', 'Unknown error')}")
            else:
                logger.info("project_files_refresher completed successfully")
                # Wait a bit for compilation to start
                import time
                time.sleep(3)
        else:
            logger.warning("Unity connection not available, skipping project_files_refresher")
        
        # Now proceed to read the compilation log
        # Get Unity Editor.log path
        localappdata = os.environ.get('LOCALAPPDATA')
        if not localappdata:
            # In WSL, try to use Windows path
            user = os.environ.get('USER', 'Unknown')
            localappdata = f"/mnt/c/Users/{user}/AppData/Local"
        
        editor_log_path = Path(localappdata) / "Unity" / "Editor" / "Editor.log"
        
        if not editor_log_path.exists():
            return {
                "success": False,
                "message": "Unity Editor.log not found",
                "compilation_logs": []
            }
        
        # Read log file
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
        
        # Find the last "* Tundra" line after compilation_start_index
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
        
        # Find "# Output" line before the Tundra marker (searching backwards)
        output_start_index = -1
        for i in range(tundra_index - 1, compilation_start_index, -1):
            if "# Output" in lines[i]:
                output_start_index = i
                break
        
        if output_start_index == -1:
            return {
                "success": False,
                "message": f"# Output not found before * Tundra from {compilation_start_index} to {tundra_index}",
                "compilation_logs": []
            }
        
        # Extract lines between "# Output" and "* Tundra"
        compilation_logs = []
        for i in range(output_start_index + 1, tundra_index):
            line = lines[i].strip()
            if line:  # Skip empty lines
                compilation_logs.append(line)
        
        return {
            "success": True,
            "message": f"Successfully read {len(compilation_logs)} lines of compilation records from {output_start_index} to {tundra_index}",
            "compilation_logs": compilation_logs
        }
        
    except Exception as e:
        logger.error(f"Error reading Unity compilation log: {str(e)}")
        return {
            "success": False,
            "message": f"Error reading log: {str(e)}",
            "compilation_logs": []
        }

# Asset Creation Strategy

@mcp.prompt()
def asset_creation_strategy() -> str:
    """Guide for discovering and using Unity MCP tools effectively."""
    global _discovered_tools
    
    # Build tools list from discovered Unity tools
    tools_list = []
    for tool in _discovered_tools:
        command_type = tool.get("commandType", "unknown")
        description = tool.get("description", "Unknown tool")
        tools_list.append(f"- `{command_type}`: {description}")
    
    # Build tools section
    if tools_list:
        tools_section = "\\n".join(tools_list)
    else:
        tools_section = "No tools discovered. Make sure Unity MCP Bridge is running and connected."
    
    return (
        f"Available Unity MCP Server Tools:\\n\\n"
        f"{tools_section}\\n\\n"
        "Tips:\\n"
        "- Create prefabs for reusable GameObjects.\\n"
        "- Always include a camera and main light in your scenes.\\n"
        "- Tools are automatically discovered from your Unity project.\\n"
    )

# Run the server
if __name__ == "__main__":
    mcp.run(transport='stdio')
