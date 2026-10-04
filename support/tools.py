from orders.models import Order, RefundRequest
from django.utils import timezone
from .tracking_data import DELIVERY_DATA
from datetime import timedelta

def get_order_details(order_id):
    try:
        order = Order.objects.get(id=order_id)
        return {
            'order_id': order.id,
            'product_name': order.product_name,
            'amount': order.amount,
            'status': order.status,
            'carrier': order.carrier,
            'tracking_number': order.tracking_number,
            'delivery_address': order.delivery,
            'ordered_on': order.created_at.strftime('%d %b %Y'),
            'days_since_order': (timezone.now() - order.created_at).days
        }
    except Order.DoesNotExist:
        return {'error': f'Order #{order_id} not found'}
    

def get_refund_history(user_id):
    refunds = RefundRequest.objects.filter(user = user_id).order_by('-created_at')

    history = []
    for refund in refunds:
        history.append({
            'order_id': refund.order.id,
            'product': refund.order.product_name,
            'reason': refund.reason,
            'status': refund.status,
            'requested_on': refund.created_at.strftime('%d %b %Y')
        })

    return {
        'total_refund_requests': len(history),
        'history': history
    }


def check_delivery_status(tracking_number, carrier):
    DEFAULT_RESPONSE = {
        "status": "Unknown",
        "last_location": "Not Available",
        "last_update": "N/A",
        "estimated_delivery": "Contact Carrier Directly",
        "delay_reason": "No Updates From Carrier",
    }
    result = DELIVERY_DATA.get(tracking_number, DEFAULT_RESPONSE)
    result['tracking_number'] = tracking_number
    result['carrier'] = carrier

    return result


def get_customer_risk_profile(user_id):
    refunds = RefundRequest.objects.filter(user=user_id)
    orders = Order.objects.filter(user=user_id)

    total_refunds = refunds.count()
    total_orders = orders.count()

    denied = refunds.filter(status='denied').count()
    approved = refunds.filter(status='approved').count()
    pending = refunds.filter(status='pending').count()

    # last 90 days refund requests
    recent_refunds = refunds.filter(created_at__gte=timezone.now() - timedelta(days=90)).count()

    if total_orders > 0:
        total_refund_to_order_ratio = round(total_refunds/total_orders, 2)
    else:
        total_refund_to_order_ratio = 0
    
    return {
        'user_id': user_id,
        'total_orders': total_orders,
        'total_refunds_requests': total_refunds,
        'refunds_last_90_days': recent_refunds,

        'denied_refunds': denied,
        'approved_refunds': approved,
        'pending_refunds': pending,

        'refund_to_order_ratio': total_refund_to_order_ratio
    }