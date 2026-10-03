from django.shortcuts import get_object_or_404, render
import json
from django.http import JsonResponse

from orders.models import Order
from support.agents import run_support_agent
from support.models import Conversation, Message


# Create your views here.
def chat(request, order_id):
    if request.method == 'POST':
        data = json.loads(request.body) 
        user_message = data.get('message')
        # print(data['message'])

        if not user_message:
            return JsonResponse({'error': 'Empty Message'}, status=400)
        
        order = get_object_or_404(Order, id=order_id)

        conv, create = Conversation.objects.get_or_create(user=request.user, order=order)
        Message.objects.create(conversation=conv, role='user', content=user_message)

        # send user message to llm
        reply = run_support_agent(user_message, conv.id, request.user.id, order.id)
        # store llm reply to database
        Message.objects.create(conversation=conv, role="assistant", content=reply)

        
        return JsonResponse({'reply': reply})

