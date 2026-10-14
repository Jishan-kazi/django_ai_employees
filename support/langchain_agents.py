from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from django.conf import settings
from langchain.tools import tool

from support.agents import MANAGER_SYSTEM_PROMPT, RISK_SYSTEM_PROMPT, SUPPORT_SYSTEM_PROMPT
from support.event_queue import DONE, publish
from support.models import AgentLog, Conversation
from .langchain_tools import get_customer_risk_profile, get_order_details, get_refund_history, check_delivery_status, search_knowledge_base
from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents.middleware import wrap_tool_call

llm = ChatAnthropic(
    model=settings.ANTHROPIC_MODEL,
    max_tokens=1024,
    api_key=settings.ANTHROPIC_API_KEY
)

SUPPORT_TOOLS = [get_order_details, get_refund_history, check_delivery_status, search_knowledge_base]
checkpointer = InMemorySaver()




def run_support_agent_langchain(user_message, conv_id, user_id, order_id):
    conversation = Conversation.objects.get(id=conv_id)

    print('support agent start')

    
    @tool
    def escalate_to_manager(case_summary:str)->dict:
        """Escalate the case to manager for refund decision. Always include customer's user_id in the case summary so manager can assess fraud risk accurately."""
        return run_manager_agent_langchain(case_summary, conv_id)
    


    @wrap_tool_call
    def log_tool_call_middleware(request, handler):

        tool_name = request.tool_call['name']
        tool_input = request.tool_call['args']

        # publish event
        event = {'type': 'tool_call', 'message': f"Calling tool {tool_name} with input {tool_input}"}
        publish(conversation.id, event)
        # log tool calling
        AgentLog.objects.create(conversation=conversation, event_type='tool_call', message=f"Calling tool {tool_name} with input {tool_input}")

        
        # TOOL CALLING
        result = handler(request)
        print('tool name==>', tool_name)
        print('tool result==>', result.content)


        # publish event
        event = {'type': 'tool_result', 'message': f"Tool {tool_name} returned: {str(result.content)[:200]}"}
        publish(conversation.id, event)
        # log tool result
        AgentLog.objects.create(conversation=conversation, event_type='tool_result', message=f"Tool {tool_name} returned: {str(result.content)[:200]}")


        return result


    support_agent = create_agent(
        model=llm, 
        tools=SUPPORT_TOOLS + [escalate_to_manager],
        system_prompt=SUPPORT_SYSTEM_PROMPT+ f'\n\nConversation is about Order #{order_id} & user:{user_id}',
        checkpointer=checkpointer,
        middleware=[log_tool_call_middleware]
    )

    config = {"configurable": {"thread_id": str(conv_id)}}

    result = support_agent.invoke(
        {"messages": [{"role": "user", "content": user_message}]},
        config=config,
    )

    
    final_message = result['messages'][-1]
    content = final_message.content

    if isinstance(content, str):
        final_reply = content
    else:
        final_reply = "\n".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )


    print('support agent final_reply===>', final_reply)


    # publish event
    event = {"type": "final", "message": f"Support Agent Final Reply: {final_reply}"}
    publish(conversation.id, event)
    AgentLog.objects.create(conversation=conversation, event_type='final', message=f"Support Agent Final Reply: {str(final_reply)[:200]}")
    publish(conversation.id, DONE)

    return final_reply
    


def run_manager_agent_langchain(case_summary, conversation_id):
    conv = Conversation.objects.get(id=conversation_id)
    print('manager agent start')
    @tool
    def assess_fraud_risk(user_id:int)->dict:
        """Consult the risk agent to assess fraud risk for a customer. Use this when refund request looks suspicious or customer has multiple refund requests. Pass the user_id to get a risk verdict."""
        return run_risk_agent_langchain(user_id, conversation_id)


    @wrap_tool_call
    def log_tool_call_middleware(request, handler):
        tool_name = request.tool_call['name']

        print('tool_name==>', tool_name)
        
        # publish event
        event = {'type': 'manager', 'message': f"Manager tool call {tool_name}: Consulting risk agent for fraud assessment..."}
        publish(conv.id, event)
        # log manager tool call
        AgentLog.objects.create(conversation=conv, event_type="manager", message=f"Manager tool call {tool_name}: Consulting risk agent for fraud assessment...")

        result = handler(request)

        print('tool_result==>', result.content)

        return result


    # publish event
    event = {'type': 'manager', 'message': f"Manager received case for review: {str(case_summary)[:200]}"}
    publish(conv.id, event)
    # log manage receive case
    AgentLog.objects.create(conversation=conv, event_type="manager", message=f"Manager received case for review: {str(case_summary)[:200]}")

    manager_agent = create_agent(
        model=llm,
        system_prompt=MANAGER_SYSTEM_PROMPT,
        middleware=[log_tool_call_middleware],
        tools=[assess_fraud_risk]
    )
    result = manager_agent.invoke({"messages": [{"role": "user", "content": case_summary}]})
    final_reply = result["messages"][-1].content

    print('decision===>', final_reply)
    # publish event
    event = {'type': 'manager', 'message': f"Manager Decision:{str(final_reply)[:200]}"}
    publish(conv.id, event)
    #log manager final decision
    AgentLog.objects.create(conversation=conv, event_type="manager", message=f"Manager Decision:{str(final_reply)[:200]}")

    return final_reply



def run_risk_agent_langchain(user_id, conversation_id):
    conv = Conversation.objects.get(id=conversation_id)
    print('risk agent start')
    # publish event
    event = {'type': 'risk', 'message': f"Risk agent received case: Starting fraud assessment for user {user_id}"}
    publish(conv.id, event)
    # log risk assessment starting
    AgentLog.objects.create(conversation=conv, event_type="risk", message=f"Risk agent received case: Starting fraud assessment for user {user_id}")

    @wrap_tool_call
    def log_tool_call_middleware(request, handler):
        tool_name = request.tool_call['name']
        # publish event
        event = {'type': 'risk', 'message': f"Risk agent tool call {tool_name}: To get customer risk profile"}
        publish(conv.id, event)
        # log risk agent tool call
        AgentLog.objects.create(conversation=conv, event_type="risk", message=f"Risk agent tool call {tool_name}: To get customer risk profile")

        result = handler(request)
        return result

    risk_agent = create_agent(
        model=llm,
        system_prompt=RISK_SYSTEM_PROMPT,
        middleware=[log_tool_call_middleware],
        tools=[get_customer_risk_profile]
    )

    result = risk_agent.invoke({"messages": [{"role": "user", "content": f"Please assess the fraud risk for user ID: {user_id}. Use your tool to get their profile and return a verdict"}]})
    final_reply = result["messages"][-1].content
    print('verdict===>', final_reply)
    # publish event
    event = {'type': 'risk', 'message': f"Risk agent verdict: {str(final_reply)[:200]}"}
    publish(conv.id, event)
    # log risk agent final verdict
    AgentLog.objects.create(conversation=conv, event_type="risk", message=f"Risk agent verdict: {str(final_reply)[:200]}")

    return final_reply

    