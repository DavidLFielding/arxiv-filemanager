"""Provides routes for the external API."""

import json

from flask.json import jsonify
from flask import Blueprint, render_template, redirect, request, url_for, \
    Response, make_response
from werkzeug.exceptions import NotFound, Forbidden, Unauthorized, \
    InternalServerError, HTTPException, BadRequest
from arxiv.base import routes as base_routes
from arxiv import status
from arxiv.users.auth import scopes
from arxiv.users.auth.decorators import scoped

from filemanager.controllers import upload

blueprint = Blueprint('upload_api', __name__, url_prefix='/filemanager/api')


@blueprint.route('/status', methods=['GET'])
def service_status() -> tuple:
    """Health check endpoint."""
    return jsonify({'status': 'OK', 'total_uploads': 1}), status.HTTP_200_OK


@blueprint.route('/', methods=['POST'])
@scoped(scopes.WRITE_UPLOAD)
def new_upload() -> tuple:
    """Initial upload where workspace (upload_id) does not yet exist.

    This requests creates a new workspace. Upload package is processed normally.

    Client response include upload_id which is necessary for subsequent requests."""

    # Optional category/archive - this is required to accurately calculate
    # whether submission is oversize.
    archive_arg = request.form.get('archive', None)

    # is this optional??
    archive_arg = request.args.get('archive')

    # Required file payload
    file = request.files.get('file', None)

    # Collect arguments and call main upload controller
    data, status_code, headers = upload.upload(None, file, archive_arg)

    return jsonify(data), status_code, headers


@blueprint.route('<int:upload_id>', methods=['GET', 'POST'])
@scoped(scopes.WRITE_UPLOAD)
def upload_files(upload_id: int) -> tuple:
    """Upload individual files or compressed archive
    and add to existing upload workspace. Multiple uploads accepted."""

    if request.method == 'POST':

        archive_arg = request.args.get('archive')

        file = request.files.get('file', None)

        # Attempt to process upload
        data, status_code, headers = upload.upload(upload_id, file, archive_arg)

    if request.method == 'GET':
        data, status_code, headers = upload.upload_summary(upload_id)

   # if request.method == 'DELETE':
    #    data, status_code, headers = upload.delete_workspace(upload_id)

    return jsonify(data), status_code, headers


@blueprint.route('<int:upload_id>', methods=['DELETE'])
@scoped(scopes.ADMIN_UPLOAD)
def workspace_delete(upload_id: int) -> tuple:
    """Delete the specified workspace."""

    data, status_code, headers = upload.delete_workspace(upload_id)

    return jsonify(data), status_code, headers


# TODO: The requests below need to be evaluated and/or implemented

# Was debating about 'manifest' request but upload GET request
# seems to do same thing (though that one returns file information
# generated during file processing.
#
# Will upload GET always return list of files?
#
# @blueprint.route('/manifest/<int:upload_id>', methods=['GET'])
# @scoped('read:upload')
# def manifest(upload_id: int) -> tuple:
#    """Manifest of files contained in upload package."""
#    #data, status_code, headers = upload.generate_manifest(upload_id)
#    return jsonify(data), status_code, headers


# Or would 'download' be a better request? 'disseminate'?
@blueprint.route('/content/<int:upload_id>', methods=['GET'])
@scoped(scopes.READ_UPLOAD)
def get_files(upload_id: int) -> tuple:
    """Return compressed archive containing files."""
    data, status_code, headers = upload.package_content(upload_id)
    return jsonify(data), status_code, headers


# This could be freeze instead of lock
@blueprint.route('/lock/<int:upload_id>', methods=['GET'])
@scoped(scopes.WRITE_UPLOAD)
def lock(upload_id: int) -> tuple:
    """Lock submission (read-only mode) while other services are
    processing (major state transitions are occurring)."""
    data, status_code, headers = upload.upload_lock(upload_id)
    return jsonify(data), status_code, headers


# This could be thaw or release instead of unlock
@blueprint.route('/unlock/<int:upload_id>', methods=['GET'])
@scoped(scopes.WRITE_UPLOAD)
def unlock(upload_id: int) -> tuple:
    """Unlock submission and enable write mode."""
    data, status_code, headers = upload.upload_unlock(upload_id)
    return jsonify(data), status_code, headers


# This could be remove or delete instead of release
@blueprint.route('/release/<int:upload_id>', methods=['GET'])
@scoped(scopes.WRITE_UPLOAD)
def release(upload_id: int) -> tuple:
    """Client indicates they are finished with submission.
    File management service is free to remove submissions files,
    or schedule files for removal at later time."""
    data, status_code, headers = upload.upload_release(upload_id)
    return jsonify(data), status_code, headers


# This could be get_logs or retrieve_logs instead of logs
@blueprint.route('/logs/<int:upload_id>', methods=['GET'])
@scoped(scopes.WRITE_UPLOAD)
def logs(upload_id: int) -> tuple:
    """Retreive log files related to submission. Indicates
    history or actions on submission package."""
    data, status_code, headers = upload.upload_logs(upload_id)
    return jsonify(data), status_code, headers


# Exception handling


@blueprint.errorhandler(NotFound)
@blueprint.errorhandler(InternalServerError)
@blueprint.errorhandler(Forbidden)
@blueprint.errorhandler(Unauthorized)
@blueprint.errorhandler(BadRequest)
@blueprint.errorhandler(NotImplementedError)
def handle_exception(error: HTTPException) -> Response:
    """
    JSON-ify the error response.

    This works just like the handlers in zero.routes.ui, but instead of
    rendering a template we are JSON-ifying the response. Note that we are
    registering the same error handler for several different exceptions, since
    we aren't doing anything that is specific to a particular exception.
    """
    content = jsonify({'reason': error.description})

    # Each Werkzeug HTTP exception has a class attribute called ``code``; we
    # can use that to set the status code on the response.
    response = make_response(content, error.code)
    return response
