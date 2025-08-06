from slack_bolt.async_app import AsyncApp
from logging import Logger
from slack_sdk import WebClient
from slack_bolt import Say, Ack, BoltContext
import os
import uuid
import re
from a2a.client import A2AClient
from a2a.types import Message, TextPart, MessageSendParams, MessageResponse

def format_response_for_slack(text):
    """Format markdown text for better display in Slack."""
    # Convert markdown tables to code blocks for better formatting
    lines = text.split('\n')
    formatted_lines = []
    in_table = False
    table_lines = []

    for line in lines:
        # Check if this is a table line (contains | and has multiple cells)
        if '|' in line and line.count('|') >= 2:
            if not in_table:
                in_table = True
                table_lines = []

            # Skip separator lines with ---
            if '---' not in line:
                table_lines.append(line)
        else:
            # We've exited a table
            if in_table:
                in_table = False
                if table_lines:
                    # Add the table as a code block
                    formatted_lines.append('```')
                    formatted_lines.extend(table_lines)
                    formatted_lines.append('```')
                    table_lines = []

            # Add the non-table line
            formatted_lines.append(line)

    # Handle case where text ends with a table
    if in_table and table_lines:
        formatted_lines.append('```')
        formatted_lines.extend(table_lines)
        formatted_lines.append('```')

    return '\n'.join(formatted_lines)


async def invoke_a2a_agent(agent_url: str, input: str, logger: Logger):
    """
    Invokes the A2A agent and returns the response.
    """
    a2a_client = A2AClient(url=agent_url, timeout=600.0)

    # Create proper Pydantic models instead of raw dictionaries
    text_part = TextPart(text=input)
    message = Message(role="user", parts=[text_part])

    # Create MessageSendParams with proper types
    message_params = MessageSendParams(
        message=message,
        metadata={}
    )

    logger.info(f"Invoking the agent: {agent_url}")
    logger.info(f"Generated messageId: {message.messageId}")

    # Debug: Print the payload being sent
    print("=== PAYLOAD DEBUG ===")
    print(f"TextPart: {text_part.model_dump()}")
    print(f"Message: {message.model_dump()}")
    print(f"MessageSendParams: {message_params.model_dump()}")
    print("=====================")

    # Convert to dict for the client
    payload = message_params.model_dump()
    response = await a2a_client.send_task(payload)
    text = ""
    # The new API returns the message directly in the result
    if response.result and response.result.parts:
        for part in response.result.parts:
            if hasattr(part, 'text'):
                # Check if the response contains an error message
                part_text = part.text
                if "failed to invoke task:" in part_text and "Error code:" in part_text:
                    # Extract the clean error message from the OpenAI error
                    import re
                    error_match = re.search(r"Error code: \d+ - \{'error': \{'message': \"([^\"]+)\"", part_text)
                    if error_match:
                        clean_error = error_match.group(1)
                        raise Exception(f"Agent error: {clean_error}")
                    else:
                        raise Exception("Agent encountered an internal error")
                text += part_text
    return text

async def mykagent_command(
    client: WebClient, ack: Ack, command, say: Say, logger: Logger, context: BoltContext
):
    await ack()

    user_id = context["user_id"]
    channel_id = context["channel_id"]
    text = command.get("text")

    # Immediately respond with the user's message and processing status
    initial_response = await client.chat_postMessage(
        channel=channel_id,
        text=f"Hello <@{user_id}>! You've asked me: \"{text}\"\n\nProcessing your request...",
    )

    # Add drumroll emoji reaction to the initial message
    await client.reactions_add(
        channel=channel_id,
        timestamp=initial_response["ts"],
        name="drumroll"
    )

    # Check if the KAGENT_A2A_URL environment variable is set
    kagent_a2a_url = os.getenv("KAGENT_A2A_URL")
    if not kagent_a2a_url:
        # TODO: Implement the logic for the /mykagent command
        await client.chat_postMessage(
            channel=channel_id,
            text="Hello! Once you set the KAGENT_A2A_URL environment variable, you can use the /mykagent command.",
        )
        return

    # Invoke the KAGENT A2A API
    try:
        response = await invoke_a2a_agent(kagent_a2a_url, text, logger)

        # Remove drumroll reaction and add success reaction
        await client.reactions_remove(
            channel=channel_id,
            timestamp=initial_response["ts"],
            name="drumroll"
        )
        await client.reactions_add(
            channel=channel_id,
            timestamp=initial_response["ts"],
            name="success"
        )

        # Format the response for better Slack display
        formatted_response = format_response_for_slack(response)

        await client.chat_postMessage(
            channel=channel_id,
            text=f"*Agent Response:*\n{formatted_response}",
        )
    except Exception as e:
        logger.error(f"Error: {e}")

        # Remove drumroll reaction and add burn-elmo reaction
        await client.reactions_remove(
            channel=channel_id,
            timestamp=initial_response["ts"],
            name="drumroll"
        )
        await client.reactions_add(
            channel=channel_id,
            timestamp=initial_response["ts"],
            name="burn-elmo"
        )

        await client.chat_postMessage(
            channel=channel_id,
            text=f"❌ An error occurred while talking to kagent: {e}",
        )


def register_handlers(app: AsyncApp):
    """
    Register all handlers for the bot.
    """

    # Commands
    app.command("/k8s-helper")(mykagent_command)