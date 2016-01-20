from django.contrib.auth.decorators import login_required
from django.core.exceptions import SuspiciousOperation
from django.shortcuts import render, redirect
from django.http import HttpResponse, HttpResponseForbidden, Http404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from apps.core.models import Service, ServiceMap, AccessToken, PointLog
from apps.core.backends import reg_service
import json
import logging
import os
import urllib


logger = logging.getLogger('sso.api')


# get call back url
def get_callback(user, service, url):
    is_test = user.profile.is_for_test
    if not is_test and not service:
        raise Http404()
    elif service:
        return service.callback_url
    return url


# /require/
@login_required
def require(request):
    name = request.GET.get('app', '')
    service = Service.objects.filter(name=name).first()

    url = request.GET.get('url', '')
    dest = get_callback(request.user, service, url)

    if name.startswith('sparcs') and not request.user.profile.sparcs_id:
        return HttpResponseForbidden()

    token = AccessToken.objects.filter(user=request.user, service=service).first()
    if token:
        logger.info('token.delete', request, hide=True)
        token.delete()

    m = ServiceMap.objects.filter(user=request.user, service=service).first()

    fail = False
    if (not m or m.unregister_time) and service:
        fail = not reg_service(request, request.user, service)

    if fail:
        d = service.cooltime - (timezone.now() - m.unregister_time).days
        return render(request, 'oauth/cooltime.html', {'service': service, 'left': d})

    while True:
        tokenid = os.urandom(10).encode('hex')
        if not AccessToken.objects.filter(tokenid=tokenid, service=service).count():
            break

    token = AccessToken(tokenid=tokenid, user=request.user, service=service)
    token.save()
    logger.info('token.create: app=%s, url=%s' % (name, url), request)
    args = {'tokenid': token.tokenid}
    return redirect(dest + '?' + urllib.urlencode(args))


# /info/
def info(request):
    tokenid = request.GET.get('tokenid', '')
    token = AccessToken.objects.filter(tokenid=tokenid).first()
    if not token:
        raise Http404()

    user = token.user
    profile = user.profile
    service = token.service
    logger.info('token.delete', request, hide=True)
    token.delete()

    m = ServiceMap.objects.filter(user=user, service=service).first()
    sid = user.username
    if m:
        sid = m.sid

    resp = {}
    resp['uid'] = user.username
    resp['sid'] = sid
    resp['email'] = user.email
    resp['first_name'] = user.first_name
    resp['last_name'] = user.last_name
    resp['gender'] = profile.gender
    if profile.birthday:
        resp['birthday'] = profile.birthday.isoformat()
    else:
        resp['birthday'] = ''
    resp['is_for_test'] = profile.is_for_test
    resp['facebook_id'] = profile.facebook_id
    resp['twitter_id'] = profile.twitter_id
    resp['kaist_id'] = profile.kaist_id
    resp['kaist_info'] = profile.kaist_info
    if profile.kaist_info_time:
        resp['kaist_info_time'] = profile.kaist_info_time.isoformat()
    else:
        resp['kaist_info_time'] = ''
    resp['sparcs_id'] = profile.sparcs_id

    return HttpResponse(json.dumps(resp), content_type='application/json')


# /point/
@csrf_exempt
def point(request):
    if request.method != 'POST':
        raise SuspiciousOperation()

    name = request.POST.get('app', '')
    service = Service.objects.filter(name=name).first()
    if not service:
        raise Http404()

    key = request.POST.get('key', '')
    if service.secret_key != key:
        raise SuspiciousOperation()

    sid = request.POST.get('sid', '')
    m = ServiceMap.objects.filter(sid=sid, service=service).first()
    if not m:
        raise Http404()

    delta = int(request.POST.get('delta', '0'))
    action = request.POST.get('action', '')

    profile = m.user.profile
    point = profile.point
    if delta:
        point += delta
        manager = m.user.point_logs
        if manager.count() >= 20:
            manager.order_by('time')[0].delete()
        PointLog(user=m.user, service=service, delta=delta, point=point, \
                 action=action).save()

        profile.point = point
        profile.save()

    return HttpResponse(json.dumps({'point':point}), content_type='application/json')

