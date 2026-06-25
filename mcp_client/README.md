# MCP Chat Client with Postgres MCP server Integration

This project demonstrates how to create a **custom MCP chat client** that connects to your MCP server (backed by a PostgreSQL employee database) and allows you to ask questions interactively.  

It uses **[MCP-Use](https://github.com/mcp-use/mcp-use)** — the open source way to connect any LLM to MCP tools and build custom agents with tool access, without relying on closed-source or proprietary solutions.

---

## 🚀 Installation

### 1. Install MCP-Use
```bash
pip install mcp-use
```

### 2. Install LangChain Providers

MCP-Use works with various LLM providers through LangChain. Install the provider package for the LLM you want to use:

```bash
# For OpenAI
pip install langchain-openai

# For Anthropic
pip install langchain-anthropic

# For Groq
pip install langchain_groq
```

## 🔑 Environment Variables

Add your API keys to a `.env` file in the project root:

```env
OPENAI_API_KEY=your_openai_key_here
ANTHROPIC_API_KEY=your_anthropic_key_here
GROQ_API_KEY=your_groq_key_here
```

## ⚙️ MCP Server Configuration

You can configure your MCP servers using a JSON file. Example:

```python
client = MCPClient.from_config_file(
    os.path.join("mcp_servers.json")
)
```

Example configuration file (`mcp_servers.json`):

```json
{
  "mcpServers": {
    "EmployeeManager": {
      "command": "C:\\Users\\90ram\\anaconda3\\envs\\mcp_server\\python",
      "args": ["E:\\__playground__\\AI\\mcp_server\\src\\main.py"],
      "env": {
        "DISPLAY": ":1"
      }
    }
  }
}
```

This tells the MCP client how to launch and connect to your Postgres-backed MCP server.

## ▶️ Running the Chat Client

Run the interactive chat client:

```bash
python mcp_chat_client.py
```

You'll see:

```
********** Interactive MCP Chat **********
Type 'exit' or 'quit' to end the conversation
Type 'clear' to clear the conversation history
******************************************
```

You can now type queries like:

```
hi

get employee EMP1001

show salary history EMP2002
```

### Example Output

![Example 1](https://github.com/user-attachments/assets/c778d870-c25e-4755-a6d1-05b9e6f6bbc8)

![Example 2](https://github.com/user-attachments/assets/76555338-9eb3-437e-bc7f-26cae310c138)
