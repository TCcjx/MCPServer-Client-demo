import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from contextlib import AsyncExitStack
from langchain_openai.chat_models import ChatOpenAI
from typing import (
    List,
    Callable,
    Any,
    Optional
)
from mcp.client.sse import sse_client

from openai import OpenAI


def get_ChatOpenAI(
        model_name: str = "glm4-chat",
        temperature: float = 0.7,
        max_tokens: int = None,
        streaming: bool = True,
        callbacks: List[Callable] = [],
        verbose: bool = True,
        local_wrap: bool = False,
        **kwargs: Any,
) -> ChatOpenAI:
    params = dict(
        streaming=streaming,
        verbose=verbose,
        callbacks=callbacks,
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )
    for k in list(params):
        if params[k] is None:
            params.pop(k)
    try:
        if local_wrap:
            params.update(
                model_name="deepseek-r1-distill-qwen",
                openai_api_base=f"http://127.0.0.1:9997/v1",
                openai_api_key="EMPTY"
            )
        else:
            params = dict(
                # model_name="deepseek/deepseek-r1/community",
                # model_name="qwen/qwen-2.5-72b-instruct",
                model_name="qwen/qwq-32b",
                base_url="https://api.ppinfra.com/v3/openai",
                api_key="sk_jMJIJ0i3AmCgnfAQneHIpzwMdixK750PEJy4ZouU5gY",
            )
        model = ChatOpenAI(**params)
    except Exception as e:
        print(e)
        model = None
    return model


class MCPClient:
    def __init__(self):
        """初始化 MCP 客户端"""
        self.model = "qwen/qwq-32b"
        self.openai_api_key = "sk_jMJIJ0i3AmCgnfAQneHIpzwMdixK750PEJy4ZouU5gY"
        self.base_url = "https://api.ppinfra.com/v3/openai"
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.client = OpenAI(api_key=self.openai_api_key, base_url=self.base_url)

    async def connect_to_sse_server(self, server_url: str):
        self._streams_context = sse_client(url=server_url)
        streams = await self._streams_context.__aenter__()
        self._session_context = ClientSession(*streams)
        self.session: ClientSession = await self._session_context.__aenter__()

        await self.session.initialize()
        print("初始化 sse 客户端...")
        print("展示tools")
        response = await self.session.list_tools()
        tools = response.tools
        print("\nConnected to server with tools:", [tool.name for tool in tools])

    async def process_query(self, query: str) -> str:
        """
        使用大模型处理并调用可用的 MCP 工具 (function calling)
        """
        messages = [{"role": "user", "content": query}]
        response = await self.session.list_tools()

        available_tools = [{
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema
            }
        } for tool in response.tools]
        print(available_tools)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=available_tools
            )
        content = response.choices[0]
        if content.finish_reason == "tool_calls":
            # 如果是使用工具，就解析工具
            tool_call = content.message.tool_calls[0]
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)

            # 执行工具
            result = await self.session.call_tool(tool_name, tool_args)
            print(f"\n\n[Calling tool {tool_name} with args {tool_args}]\n\n")

            # 将模型返回的调用哪个工具数据和工具执行完成后的数据都存入messages中
            messages.append(content.message.model_dump())
            messages.append({
                "role": "tool",
                "content": result.content[0].text,
                "tool_call_id": tool_call.id,
            })

            # 将上面的结果再返回给大模型用于生成最终的结果
            response = self.client.chat.completions.create(
            model=self.model,
            messages=messages
            )
            return response.choices[0].message.content
        return content.message.content
    async def chat_loop(self):
        """运行交互式聊天循环"""
        print("\n MCP 客户端已启动！输入 'quit' 退出")
        while True:
            try:
                query = input("\n你: ").strip()
                if query.lower() == 'quit':
                    break
                response = await self.process_query(query)
                print(f"\n OpenAI: {response}")
            except Exception as e:
                print(f"error {e}")

    async def cleanup(self):
        if self._session_context:
            await self._session_context.__aexit__(None, None, None)
        if self._streams_context:
            await self._streams_context.__aexit__(None, None, None)


async def main():
    # if len(sys.argv) < 2:
    #     print("Usage: uv run client.py <URL of SSE MCP server (i.e. http://localhost:8080/sse)>")
    #     sys.exit(1)
    client = MCPClient()
    try:
        await client.connect_to_sse_server(server_url="http://192.168.102.7:7777/sse")
        await client.chat_loop()
    finally:
        await client.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
