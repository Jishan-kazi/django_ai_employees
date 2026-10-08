from anthropic import Anthropic
from django.conf import settings

from support.event_queue import publish
from support.models import AgentLog, Conversation
from .tools import get_order_details, get_refund_history, check_delivery_status, get_customer_risk_profile

client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
anthropic_model = settings.ANTHROPIC_MODEL

# SUPPORT SYSTEM PROMPT --> Maya's Job Description
SUPPORT_SYSTEM_PROMPT = """
You are Maya, a customer support agent at CoolBreeze AC.
You help customers with issues related to their AC orders.

Your responsibilities:
- Always use your tools to gather facts before responding
- Check order details when customer mentions their order
- Check refund history before making any refund decisions
- Be empathetic but honest

Your personality:
- Friendly and professional
- Patient even when customer is angry
- Clear and concise in your replies
- No Emojis

Important rules:
- Always check order details first before responding
- Never approve or deny a refund yourself
- If refund decision is needed — tell customer you are checking with your team
- Never use bold text, bullet points or any markdown formatting. Plain text only.
- Keep replies concise and conversational. Maximum 3-4 sentences. No long paragraphs
"""

MANAGER_SYSTEM_PROMPT = """
You are a senior support manager at CoolBreeze AC.
A support agent has escalated a customer case to you for a refund decision.

Your responsibilities:
- Review the case summary carefully
- Consider the customer's refund history
- Make a fair and final refund decision
- Give a clear reason for your decision

Your decision options:
- Approve refund — if the case is genuine and within policy
- Deny refund — if the case is suspicious or outside policy
- Escalate to risk team — if you suspect fraud

Important rules:
- Be fair but firm
- Base decision on facts — not emotions
- Always give a specific reason for your decision
- Keep your response concise and professional
"""

RISK_SYSTEM_PROMPT = """
You are a fraud risk analyst at CoolBreeze AC.
A support manager has sent you a customer profile for risk assessment.

Your job:
- Analyse the customer's order and refund patterns
- Identify suspicious behaviour
- Return a clear risk verdict

Risk levels:
- LOW — genuine customer, normal behaviour
- MEDIUM — some suspicious signals, proceed with caution
- HIGH — clear fraud pattern, recommend denial

Your response format:
- Risk Level: LOW / MEDIUM / HIGH
- Key Signals: what you found suspicious or genuine
- Recommendation: what manager should do

Important:
- Be objective — base verdict on data only
- One bad refund does not make someone fraudulent
- Look for patterns — not isolated incidents
"""


# SUPPORT TOOLS SCHEMA --> Tool Schema that ai agents will read
SUPPORT_TOOLS = [
    {
        'name': 'get_order_details',
        'description': 'Fetch the complete order details including product name, order amount, status, carrier, tracking number, delivery address, ordered on & days since order was placed. Use this when customer mentions their order or complains about delivery.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'order_id':{
                    'type': 'integer',
                    'description': 'The order ID to look up'
                } 
            },
            'required': ['order_id']
        }
    },
    {
        "name": "get_refund_history",
        "description": "Get complete refund history for a user. Use this before making any refund related decisions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "The user ID to check refund history for"
                }
            },
            "required": ["user_id"]
        }
    },

    {
        "name": "check_delivery_status",
        "description": "Check current delivery status using tracking number and carrier. Use this when customer complains about delayed or missing delivery.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tracking_number": {
                    "type": "string",
                    "description": "The shipment tracking number"
                },
                "carrier": {
                    "type": "string",
                    "description": "The carrier name for example BlueDart or Delhivery"
                }
            },
            "required": ["tracking_number", "carrier"]
        }
    },

    {
        "name": "escalate_to_manager",
        "description": "Escalate the case to manager for refund decision. Always include customer's user_id in the case summary so manager can assess fraud risk accurately.",
        "input_schema": {
            "type": "object",
            "properties": {
                "case_summary": {
                    "type": "string",
                    "description": "Complete case summary. Must include: customer user_id, order details, refund history and complaint. Format: Start with 'Customer User ID: X' on the first line."
                }
            },
            "required": ["case_summary"]
        }
    },
]

MANAGER_TOOLS = [
   {
        'name': 'assess_fraud_risk',
        "description": "Consult the risk agent to assess fraud risk for a customer. Use this when refund request looks suspicious or customer has multiple refund requests. Pass the user_id to get a risk verdict.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "The user ID to assess fraud risk for"
                }
            },
            "required": ["user_id"]
        }
   }
]

RISK_TOOLS = [
   {
        'name': 'get_customer_risk_profile',
        "description": "Get complete risk profile for a customer including order history, refund patterns and ratio. Use this to assess fraud risk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "The user ID to assess risk for"
                }
            },
            "required": ["user_id"]
        }
   }
]


# execute_tool() function --> bridge between claude & tools
def execute_tool(tool_name, tool_input, conversation_id=None):
    if (tool_name == 'get_order_details'):
      return get_order_details(tool_input['order_id'])
    
    if (tool_name == 'get_refund_history'):
       return get_refund_history(tool_input['user_id'])
    
    if (tool_name == 'check_delivery_status'):
       return check_delivery_status(tool_input['tracking_number'], tool_input['carrier'])
    
    if tool_name == 'escalate_to_manager':
       case_summary = tool_input['case_summary']
       print('escalating to manager====>', case_summary)
       decision = run_manager_agent(case_summary, conversation_id)
       print('decision=====>', decision)
       return decision
    
    if tool_name == 'assess_fraud_risk':
        user_id = tool_input['user_id']
        print('starting fraud assessment for user id', user_id)
        verdict = run_risk_agent(user_id, conversation_id)
        print('verdict===>', verdict)
        return verdict

    if tool_name == 'get_customer_risk_profile':
        return get_customer_risk_profile(tool_input['user_id'])
        

        


# Agent loop --> While loop that loops until the task is done
def run_support_agent(user_message, conv_id, user_id, order_id):
   
    conversation = Conversation.objects.get(id=conv_id)

    conversation_messages = []
    for msg in conversation.messages.order_by('created_at'):
       conversation_messages.append({
          'role': msg.role,
          'content': msg.content
       })


    while True:

        response = client.messages.create(
            max_tokens=1024,
            model=anthropic_model,
            system=SUPPORT_SYSTEM_PROMPT + f'\n\nConversation is about Order #{order_id} & user:{user_id}',
            messages=conversation_messages,
            tools=SUPPORT_TOOLS
        )

        if response.stop_reason == 'tool_use':

            tool_result = []
            for block in response.content:
              if block.type == 'tool_use':

                # publish event
                event = {'type': 'tool_call', 'message': f"Calling tool {block.name} with input {block.input}"}
                publish(conversation.id, event)
                # log tool calling
                AgentLog.objects.create(conversation=conversation, event_type='tool_call', message=f"Calling tool {block.name} with input {block.input}")

                result = execute_tool(block.name, block.input, conv_id)

                # publish event
                event = {'type': 'tool_result', 'message': f"Tool {block.name} returned: {str(result)[:200]}"}
                publish(conversation.id, event)
                # log tool result
                AgentLog.objects.create(conversation=conversation, event_type='tool_result', message=f"Tool {block.name} returned: {str(result)[:200]}")

                tool_result.append({
                    'type': 'tool_result',
                    'tool_use_id': block.id,
                    'content': str(result)
                })
            
            conversation_messages.append({
                'role': 'assistant',
                'content': response.content
            })
            conversation_messages.append({
               'role': 'user',
               'content': tool_result
            })
                

        else:

            final_reply = next(
                (block.text
                for block in response.content
                if block.type == "text"),
                ""
            )

            # publish event
            event = {"type": "final", "message": f"Support Agent Final Reply: {final_reply}"}
            publish(conversation.id, event)
            # log final reply
            AgentLog.objects.create(conversation=conversation, event_type='final', message=f"Support Agent Final Reply: {str(final_reply)[:200]}")

            return final_reply
        

def run_manager_agent(case_summary, conversation_id):
    conv = Conversation.objects.get(id=conversation_id)

    # publish event
    event = {'type': 'manager', 'message': f"Manager received case for review: {str(case_summary)[:200]}"}
    publish(conv.id, event)
    # log manage receive case
    AgentLog.objects.create(conversation=conv, event_type="manager", message=f"Manager received case for review: {str(case_summary)[:200]}")

    manager_messages = [{
       'role': 'user',
       'content': case_summary
    }]
    
    while True:
        response = client.messages.create(
            max_tokens=1024,
            model=anthropic_model,
            system=MANAGER_SYSTEM_PROMPT,
            messages=manager_messages,
            tools=MANAGER_TOOLS
        )

        if response.stop_reason == 'tool_use':
            tool_result = []
            for block in response.content:
              if block.type == 'tool_use':

                # publish event
                event = {'type': 'manager', 'message': f"Manager tool call {block.name}: Consulting risk agent for fraud assessment..."}
                publish(conv.id, event)
                # log manager tool call
                AgentLog.objects.create(conversation=conv, event_type="manager", message=f"Manager tool call {block.name}: Consulting risk agent for fraud assessment...")

                result = execute_tool(block.name, block.input, conversation_id)
                tool_result.append({
                   'type': 'tool_result',
                   'tool_use_id': block.id,
                   'content': str(result)
                })

            manager_messages.append({
               'role': 'assistant',
               'content': response.content
            })

            manager_messages.append({
               'role': 'user',
               'content': tool_result
            })

        else:
            final_reply = next((block.text for block in response.content if block.type=='text'), '')

            # publish event
            event = {'type': 'manager', 'message': f"Manager Decision:{str(final_reply)[:200]}"}
            publish(conv.id, event)
            #log manager final decision
            AgentLog.objects.create(conversation=conv, event_type="manager", message=f"Manager Decision:{str(final_reply)[:200]}")
            return final_reply
        

def run_risk_agent(user_id, conversation_id):
    conv = Conversation.objects.get(id=conversation_id)

    # publish event
    event = {'type': 'risk', 'message': f"Risk agent received case: Starting fraud assessment for user {user_id}"}
    publish(conv.id, event)
    # log risk assessment starting
    AgentLog.objects.create(conversation=conv, event_type="risk", message=f"Risk agent received case: Starting fraud assessment for user {user_id}")

    risk_messages = [
        {
            'role': 'user',
            'content': f"Please assess the fraud risk for user ID: {user_id}. Use your tool to get their profile and return a verdict"
        }
    ]

    while True:
        response = client.messages.create(
            model=anthropic_model,
            max_tokens=1024,
            system=RISK_SYSTEM_PROMPT,
            messages=risk_messages,
            tools=RISK_TOOLS
        )

        if response.stop_reason == 'tool_use':
           
            tool_result = []
            for block in response.content:
              if block.type == 'tool_use':

                # publish event
                event = {'type': 'risk', 'message': f"Risk agent tool call {block.name}: To get customer risk profile"}
                publish(conv.id, event)
                # log risk agent tool call
                AgentLog.objects.create(conversation=conv, event_type="risk", message=f"Risk agent tool call {block.name}: To get customer risk profile")

                print('executing risk tool', block.name)
                print('risk tool input', block.input)
                result = execute_tool(block.name, block.input)

                tool_result.append({
                   'type': 'tool_result',
                   'tool_use_id': block.id,
                   'content': str(result)
                })

            risk_messages.append({
               'role': 'assistant',
               'content': response.content
            })

            risk_messages.append({
               'role': 'user',
               'content': tool_result
            })
                

        else:
            final_reply = next(
                (block.text for block in response.content if block.type == 'text'),
                ''
            )

            # publish event
            event = {'type': 'risk', 'message': f"Risk agent verdict: {str(final_reply)[:200]}"}
            publish(conv.id, event)
            # log risk agent final verdict
            AgentLog.objects.create(conversation=conv, event_type="risk", message=f"Risk agent verdict: {str(final_reply)[:200]}")

            return final_reply



