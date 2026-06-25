import asyncio
import os
from dotenv import load_dotenv
#from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from mcp_use import MCPAgent, MCPClient

async def run_memory_chat():
    """Run an interactive chat session with memory using MCPAgent and MCPClient."""
    
    # Load environment variables
    load_dotenv()

    os.environ["GROQ_API_KEY"] = os.getenv("GROQ_API_KEY")

    # Create MCPClient from config file
    client = MCPClient.from_config_file(
        os.path.join(os.path.dirname(__file__), "mcp_servers.json")
    )

    # Create LLM
    #llm = ChatOpenAI(model="gpt-4o")
    # Alternative models:
    # llm = ChatAnthropic(model="claude-3-5-sonnet-20240620")
    llm = ChatGroq(model="llama-3.3-70b-versatile")

    #llm = ChatGroq(model="qwen-qwq-32b")

    # Create agent with the client
    agent = MCPAgent(llm=llm, client=client, max_steps=15, memory_enabled=True)

    print("\n********** Interactive MCP Chat **********")
    print("Type 'exit' or 'quit' to end the conversation")
    print("Type 'clear' to clear the conversation history")
    print("******************************************\n")

    try:
        # Main chat loop
        while True:
            user_input = input("\nYou: ")

            # Exit command
            if user_input.lower() in ['exit', 'quit']:
                print("Ending conversation.")
                break

            # Clear history command
            if user_input.lower() == 'clear':
                agent.clear_conversation_history()
                print("Conversation history cleared.")
                continue

            # Get response from agent
            print("\nAssistant:", end=" ", flush=True)

            try:
                response = await agent.run(user_input)
                print("\n\n")
                print(response)

            except Exception as e:
                print(f"\nError: {e}")

    finally:
        if client and client.sessions:
            await client.close_all_sessions()

if __name__ == "__main__":
    asyncio.run(run_memory_chat())