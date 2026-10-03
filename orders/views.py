from django.shortcuts import render, get_object_or_404

from support.models import Conversation
from .models import Order, RefundRequest
from django.contrib.auth.decorators import login_required
# Create your views here.

@login_required
def order_list(request):
    orders = Order.objects.filter(user = request.user)
    context = {
        'orders': orders
    }

    return render(request, 'orders/order_list.html', context)

@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    refunds = RefundRequest.objects.filter(order=order_id, user=request.user)

    try:
        conversation = Conversation.objects.get(user=request.user, order=order)
        previous_messages = conversation.messages.order_by('created_at')
    except Conversation.DoesNotExist:
        conversation = None
        previous_messages = []

    context = {
        'order': order,
        'refunds': refunds,
        'conversation': conversation,
        'previous_messages': previous_messages
    }

    return render(request, 'orders/order_detail.html', context)
