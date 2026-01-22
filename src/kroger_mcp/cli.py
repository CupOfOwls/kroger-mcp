#!/usr/bin/env python3
"""
CLI entry point for Kroger MCP server
"""

import argparse
import os

def main():
    """CLI entry point with argument parsing"""
    parser = argparse.ArgumentParser(
        description="Kroger MCP Server - FastMCP server for Kroger API integration"
    )
    
    parser.add_argument(
        "--client-id", 
        help="Kroger API client ID (can also use KROGER_CLIENT_ID env var)"
    )
    parser.add_argument(
        "--client-secret", 
        help="Kroger API client secret (can also use KROGER_CLIENT_SECRET env var)"
    )
    parser.add_argument(
        "--redirect-uri", 
        default="http://localhost:8000/callback",
        help="OAuth redirect URI (default: http://localhost:8000/callback)"
    )
    parser.add_argument(
        "--zip-code", 
        help="Default zip code for location searches"
    )
    parser.add_argument(
        "--transport", 
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
        help="Transport protocol (default: stdio)"
    )
    parser.add_argument(
        "--host", 
        default="127.0.0.1",
        help="Host for HTTP transports (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", 
        type=int,
        default=8000,
        help="Port for HTTP transports (default: 8000)"
    )
    
    args = parser.parse_args()
    
    # Set environment variables from CLI args if provided
    if args.client_id:
        os.environ["KROGER_CLIENT_ID"] = args.client_id
    if args.client_secret:
        os.environ["KROGER_CLIENT_SECRET"] = args.client_secret
    if args.redirect_uri:
        os.environ["KROGER_REDIRECT_URI"] = args.redirect_uri
    if args.zip_code:
        os.environ["KROGER_USER_ZIP_CODE"] = args.zip_code
    
    # Import and create server
    from kroger_mcp.server import create_server
    
    server = create_server()
    
    # Run with specified transport
    if args.transport == "stdio":
        server.run()
    elif args.transport == "streamable-http":
        server.run(transport="streamable-http", host=args.host, port=args.port)
    elif args.transport == "sse":
        server.run(transport="sse", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
