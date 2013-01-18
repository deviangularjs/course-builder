# Copyright 2012 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Handlers that manages Announcements."""

__author__ = 'Saifu Angto (saifu@google.com)'

import datetime
import json
import urllib
from controllers.utils import BaseHandler
from models.models import Student
import models.transforms as transforms
import modules.announcements.samples as samples
import modules.announcements.schema as schema
from modules.oeditor.oeditor import ObjectEditor
from google.appengine.api import users
from google.appengine.ext import db


class AnnouncementsRights(object):
    """Manages view/edit rights for announcements."""

    @classmethod
    def can_view(cls):
        return True

    @classmethod
    def can_edit(cls):
        return users.is_current_user_admin()

    @classmethod
    def can_delete(cls):
        return cls.can_edit()

    @classmethod
    def can_add(cls):
        return cls.can_edit()


class AnnouncementsHandler(BaseHandler):
    """Handler for announcements."""

    default_action = 'list'
    get_actions = [default_action, 'edit']
    post_actions = ['add', 'delete']

    @classmethod
    def get_child_routes(cls):
        """Add child handlers for REST."""
        return [('/rest/announcements/item', ItemRESTHandler)]

    def get_action_url(self, action, key=None):
        args = {'action': action}
        if key:
            args['key'] = key
        return self.canonicalize_url(
            '/announcements?%s' % urllib.urlencode(args))

    def apply_rights(self, items):
        """Filter out items that current user can't see."""
        if AnnouncementsRights.can_edit():
            return items

        allowed = []
        for item in items:
            if not item.is_draft:
                allowed.append(item)

        return allowed

    def get(self):
        """Handles GET."""
        action = self.request.get('action')
        if not action:
            action = AnnouncementsHandler.default_action

        if not action in AnnouncementsHandler.get_actions:
            self.error(404)
            return

        handler = getattr(self, 'get_%s' % action)
        if not handler:
            self.error(404)
            return

        return handler()

    def post(self):
        """Handles POST."""
        action = self.request.get('action')
        if not action or not action in AnnouncementsHandler.post_actions:
            self.error(404)
            return

        handler = getattr(self, 'post_%s' % action)
        if not handler:
            self.error(404)
            return

        return handler()

    def format_items_for_template(self, items):
        """Formats a list of entities into template values."""
        template_items = []
        for item in items:
            item = transforms.entity_to_dict(item)

            # add 'edit' actions
            if AnnouncementsRights.can_edit():
                item['edit_action'] = self.get_action_url('edit', item['key'])
                item['delete_action'] = self.get_action_url(
                    'delete', item['key'])

            template_items.append(item)

        output = {}
        output['children'] = template_items

        # add 'add' action
        if AnnouncementsRights.can_edit():
            output['add_action'] = self.get_action_url('add')

        return output

    def put_sample_announcements(self):
        """Loads sample data into a database."""
        items = []
        for item in samples.SAMPLE_ANNOUNCEMENTS:
            entity = AnnouncementEntity()
            transforms.dict_to_entity(entity, item)
            entity.put()
            items.append(entity)
        return items

    def get_list(self):
        """Shows a list of announcements."""
        user = self.personalize_page_and_get_user()
        if not user:
            self.redirect(users.create_login_url(self.request.uri))
            return

        student = Student.get_enrolled_student_by_email(user.email())
        if not student:
            self.redirect('/preview')
            return

        # TODO(psimakov): cache this page and invalidate the cache on update
        items = AnnouncementEntity.all().order('-date').fetch(1000)
        if not items:
            items = self.put_sample_announcements()

        self.template_value['announcements'] = self.format_items_for_template(
            self.apply_rights(items))
        self.template_value['navbar'] = {'announcements': True}
        self.render('announcements.html')

    def get_edit(self):
        """Shows an editor for an announcement."""
        if not AnnouncementsRights.can_edit():
            self.error(401)
            return

        key = self.request.get('key')

        exit_url = self.canonicalize_url(
            '/announcements#%s' % urllib.quote(key, safe=''))
        rest_url = self.canonicalize_url('/rest/announcements/item')
        form_html = ObjectEditor.get_html_for(
            self, schema.SCHEMA_JSON, schema.SCHEMA_ANNOTATIONS_DICT,
            key, rest_url, exit_url)
        self.template_value['navbar'] = {'announcements': True}
        self.template_value['content'] = form_html
        self.render('bare.html')

    def post_delete(self):
        """Deletes an announcement."""
        if not AnnouncementsRights.can_delete():
            self.error(401)
            return

        key = self.request.get('key')
        entity = AnnouncementEntity.get(key)
        if entity:
            entity.delete()
        self.redirect('/announcements')

    def post_add(self):
        """Adds a new announcement and redirects to an editor for it."""
        if not AnnouncementsRights.can_add():
            self.error(401)
            return

        entity = AnnouncementEntity()
        entity.title = 'Sample Announcement'
        entity.date = datetime.datetime.now().date()
        entity.html = 'Here is my announcement!'
        entity.is_draft = True
        entity.put()
        self.redirect(self.get_action_url('edit', entity.key()))


def send_json_response(handler, status_code, message, payload_dict=None):
    """Formats and sends out a JSON REST response envelope and body."""
    response = {}
    response['status'] = status_code
    response['message'] = message
    if payload_dict:
        response['payload'] = json.dumps(payload_dict)
    handler.response.write(json.dumps(response))


class ItemRESTHandler(BaseHandler):
    """Provides REST API for an announcement."""

    def get(self):
        """Handles REST GET verb and returns an object as JSON payload."""
        key = self.request.get('key')
        try:
            entity = AnnouncementEntity.get(key)
        except db.BadKeyError:
            entity = None

        if not entity:
            send_json_response(self, 404, 'Object not found.', {'key': key})
        else:
            json_payload = transforms.dict_to_json(transforms.entity_to_dict(
                entity), schema.SCHEMA_DICT)
            send_json_response(self, 200, 'Success.', json_payload)

    def put(self):
        """Handles REST PUT verb with JSON payload."""
        request = json.loads(self.request.get('request'))
        key = request.get('key')

        if not AnnouncementsRights.can_edit():
            send_json_response(self, 401, 'Access denied.', {'key': key})
            return

        entity = AnnouncementEntity.get(key)
        if not entity:
            send_json_response(self, 404, 'Object not found.', {'key': key})
            return

        payload = request.get('payload')
        transforms.dict_to_entity(entity, transforms.json_to_dict(
            json.loads(payload), schema.SCHEMA_DICT))
        entity.put()

        send_json_response(self, 200, 'Saved.')


class AnnouncementEntity(db.Model):
    """A class that represents a persistent database entity of announcement."""
    title = db.StringProperty()
    date = db.DateProperty()
    html = db.TextProperty()
    is_draft = db.BooleanProperty()
