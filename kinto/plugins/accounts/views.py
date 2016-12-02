import functools

import colander
from pyramid.settings import aslist
from pyramid.exceptions import HTTPForbidden
from pyramid.security import Authenticated, Everyone

from kinto.core import resource
from kinto.core.resource.viewset import ShareableViewSet
from kinto.core import utils
from kinto.core import authorization
from kinto.views import NameGenerator
from kinto.core.errors import raise_invalid, http_error


class AccountSchema(resource.ResourceSchema):
    password = colander.SchemaNode(colander.String())


@resource.register()
class Account(resource.ShareableResource):

    schema = AccountSchema

    def __init__(self, request, context):
        context.is_anonymous = Authenticated not in request.effective_principals
        context.is_administrator = len(set(context.allowed_principals(permission='write')) &
                                       set(request.prefixed_principals)) > 0
        super(Account, self).__init__(request, context)

        if self.model.current_principal == Everyone:
            # Creation is anonymous, but author with write perm is this:
            # XXX: only works if policy name is account in settings.
            self.model.current_principal = 'account:%s' % self.model.parent_id

    def get_parent_id(self, request):
        # The whole challenge here is that we want to isolate what
        # authenticated users can list, but give access to everything to
        # administrators.
        # Plus when anonymous create accounts, we have to set their parent id
        # to the same value they would obtain when authenticated.
        if self.context.is_administrator:
            if self.context.on_collection:
                # Admin see all accounts.
                return '*'
            else:
                # No pattern matching for admin on single record.
                return request.matchdict['id']

        if not self.context.is_anonymous:
            # Authenticated users see their own account only.
            return request.selected_userid

        # Anonymous creation with PUT.
        if 'id' in request.matchdict:
            return request.matchdict['id']

        try:
            # Anonymous creation with POST.
            return request.json['data']['id']
        except (ValueError, KeyError) as e:
            # Anonymous GET, or bad POST.
            return '__no_match__'

    def collection_post(self):
        result = super(Account, self).collection_post()
        if self.context.is_anonymous and self.request.response.status_code == 200:
            error_details = {
                'message': 'User %r already exists' % result['data']['id']
            }
            raise http_error(HTTPForbidden(), **error_details)
        return result

    def process_record(self, new, old=None):
        new = super(Account, self).process_record(new, old)

        # XXX: bcrypt whatever
        # new["password"] = bcrypt(...)

        # Administrators can reach other accounts. Anonymous have no selected_userid.
        if self.context.is_administrator or self.context.is_anonymous:
            return new

        # Otherwise, we force the id to match the authenticated username.
        if new[self.model.id_field] != self.request.selected_userid:
            error_details = {
                'name': 'data',
                'description': 'Username and account id do not match.',
            }
            raise_invalid(self.request, **error_details)

        return new
