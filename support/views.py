from django.shortcuts import get_object_or_404, render
import json
from django.http import JsonResponse, StreamingHttpResponse

from orders.models import Order
from support.agents import run_support_agent
from support.event_queue import publish, subscribe, unsubscribe
from support.models import Conversation, Message
from django.contrib.admin.views.decorators import staff_member_required


# Create your views here.
def chat(request, order_id):
    if request.method == 'POST':
        data = json.loads(request.body) 
        user_message = data.get('message')

        if not user_message:
            return JsonResponse({'error': 'Empty Message'}, status=400)
        
        order = get_object_or_404(Order, id=order_id)

        conv, create = Conversation.objects.get_or_create(user=request.user, order=order)

        # publish event
        event = {'type': 'user_message', 'message': user_message, 'name': request.user.first_name}
        publish(conv.id, event)
        Message.objects.create(conversation=conv, role='user', content=user_message)

        # send user message to llm
        reply = run_support_agent(user_message, conv.id, request.user.id, order.id)

        # publish event
        event = {'type': 'assistant_message', 'message': reply, 'name': 'Maya'}
        publish(conv.id, event)
        # store llm reply to database
        Message.objects.create(conversation=conv, role="assistant", content=reply)

        
        return JsonResponse({'reply': reply})

@staff_member_required
def dashboard(request):
    conversations = Conversation.objects.all()
    context = {
        'conversations': conversations
    }
    return render(request, 'support/dashboard.html', context)

@staff_member_required
def conversation_detail(request, conversation_id):
    conversation = get_object_or_404(Conversation, id=conversation_id)
    messages = conversation.messages.all().order_by('created_at')
    agentlogs = conversation.agentlogs.all().order_by('created_at')
    context = {
        'conversation': conversation,
        'messages': messages,
        'agentlogs': agentlogs
    }

    return render(request, 'support/conversation_detail.html', context)

@staff_member_required
def conversation_stream(request, conversation_id):
    def event_stream(conversation_id):
        q = subscribe(conversation_id)

        try:
            while True:
                event = q.get()
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            unsubscribe(conversation_id, q)

    return StreamingHttpResponse(event_stream(conversation_id), content_type="text/event-stream")