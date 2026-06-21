# from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

# # Create FastAPI app
# app = FastAPI()

# Create MCP server
mcp = FastMCP('Finance MCP server')

# Define MCP tools
@mcp.tool()
def great(name: str):
    return f"Hello {name}, MCP working!"

@mcp.tool()
def get_invoice_status(invoice_id: str):
    data = {
        'INV1001': 'Paid',
        'INV1002': 'Pending',
        'INV1003': 'Failed'
    }
    return data.get(invoice_id, 'Not found')

# # Add a root route for browser testing
# @app.get("/")
# def root():
#     return {"message": "Finance MCP server is running"}

# Run MCP server on FastAPI app
if __name__ == "__main__":
    mcp.run(
        transport="streamable-http"
        # host="0.0.0.0",
        # port=8000,
        # app=app   # <-- pass your FastAPI app here
    )
