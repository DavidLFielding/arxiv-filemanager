"""Provides routes for the external API."""

import json

from flask.json import jsonify
from flask import Blueprint, render_template, redirect, request, url_for, \
    Response, make_response, send_file
from werkzeug.exceptions import NotFound, Forbidden, Unauthorized, \
    InternalServerError, HTTPException, BadRequest
from arxiv.base import routes as base_routes
from arxiv import status
from arxiv.users import domain as auth_domain
from arxiv.users.auth import scopes

from arxiv.users.auth.decorators import scoped

from filemanager.services import uploads
from filemanager.controllers import upload

blueprint = Blueprint('upload_api', __name__, url_prefix='/filemanager/api')


def is_owner(session: auth_domain.Session, upload_id: str, **kwargs) -> bool:
    """User must be the upload owner, or an admin."""
    upload_obj = uploads.retrieve(upload_id)
    if upload_obj is None:
        return True

    return session.user.user_id == uploads.retrieve(upload_id).owner_user_id


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
    data, status_code, headers = upload.upload(None, file, archive_arg,
                                               request.session.user)

    return jsonify(data), status_code, headers


@blueprint.route('<int:upload_id>', methods=['POST'])
@scoped(scopes.WRITE_UPLOAD, authorizer=is_owner)
def upload_files(upload_id: int) -> tuple:
    """Upload individual files or compressed archive
    and add to existing upload workspace. Multiple uploads accepted."""
    archive_arg = request.form.get('archive')
    ancillary = request.form.get('ancillary', None) == 'True'
    file = request.files.get('file', None)
    # Attempt to process upload
    data, status_code, headers = upload.upload(upload_id, file, archive_arg,
                                               request.session.user,
                                               ancillary=ancillary)
    return jsonify(data), status_code, headers


# Separated this out so that we can support auth granularity. -E
@blueprint.route('<int:upload_id>', methods=['GET'])
@scoped(scopes.READ_UPLOAD, authorizer=is_owner)
def get_upload_files(upload_id: int) -> tuple:
    data, status_code, headers = upload.upload_summary(upload_id)
    return jsonify(data), status_code, headers


@blueprint.route('<int:upload_id>/<path:public_file_path>', methods=['DELETE'])
@scoped(scopes.DELETE_UPLOAD_FILE, authorizer=is_owner)
def delete_file(upload_id: int, public_file_path: str) -> tuple:
    """Delete individual file."""
    data, status_code, headers = upload.client_delete_file(upload_id,
                                                           public_file_path)
    return jsonify(data), status_code, headers

# File and workspace deletion

@blueprint.route('<int:upload_id>/delete_all', methods=['POST'])
@scoped(scopes.WRITE_UPLOAD, authorizer=is_owner)
def delete_all_files(upload_id: int) -> tuple:
    """Delete all files in specified workspace."""
    data, status_code, headers = upload.client_delete_all_files(upload_id)
    return jsonify(data), status_code, headers


@blueprint.route('<int:upload_id>', methods=['DELETE'])
@scoped(scopes.DELETE_UPLOAD_WORKSPACE)
def workspace_delete(upload_id: int) -> tuple:
    """Delete the specified workspace."""
    data, status_code, headers = upload.delete_workspace(upload_id)
    return jsonify(data), status_code, headers


# Lock and unlock upload workspace

@blueprint.route('/<int:upload_id>/lock', methods=['POST'])
@scoped(scopes.WRITE_UPLOAD, authorizer=is_owner)
def lock(upload_id: int) -> tuple:
    """Lock submission (read-only mode) while other services are
    processing (major state transitions are occurring)."""
    data, status_code, headers = upload.upload_lock(upload_id)
    return jsonify(data), status_code, headers


# This could be thaw or release instead of unlock
@blueprint.route('/<int:upload_id>/unlock', methods=['POST'])
@scoped(scopes.WRITE_UPLOAD, authorizer=is_owner)
def unlock(upload_id: int) -> tuple:
    """Unlock submission and enable write mode."""
    data, status_code, headers = upload.upload_unlock(upload_id)
    return jsonify(data), status_code, headers


# This could be remove or delete instead of release
@blueprint.route('/<int:upload_id>/release', methods=['POST'])
@scoped(scopes.WRITE_UPLOAD, authorizer=is_owner)
def release(upload_id: int) -> tuple:
    """Client indicates they are finished with submission.
    File management service is free to remove submissions files,
    or schedule files for removal at later time."""
    data, status_code, headers = upload.upload_release(upload_id)
    return jsonify(data), status_code, headers


# This could be remove or delete instead of release
@blueprint.route('/<int:upload_id>/unrelease', methods=['POST'])
@scoped(scopes.WRITE_UPLOAD, authorizer=is_owner)
def unrelease(upload_id: int) -> tuple:
    """Client indicates they are finished with submission.
    File management service is free to remove submissions files,
    or schedule files for removal at later time."""
    data, status_code, headers = upload.upload_unrelease(upload_id)
    return jsonify(data), status_code, headers


# Get content

@blueprint.route('/<int:upload_id>/content', methods=['HEAD'])
@scoped(scopes.READ_UPLOAD)
def check_upload_content_exists(upload_id: int) -> tuple:
    """
    Verify that upload content exists.

    Returns an ``ETag`` header with the current source package checksum.
    """
    data, status_code, headers = upload.check_upload_content_exists(upload_id)
    return jsonify(data), status_code, headers


@blueprint.route('/<int:upload_id>/content', methods=['GET'])
@scoped(scopes.READ_UPLOAD)
def get_upload_content(upload_id: int) -> tuple:
    """
    Get the upload content as a compressed tarball.

    Returns a stream with mimetype ``application/tar+gzip``, and an ``ETag``
    header with the current source package checksum.
    """
    data, status_code, headers = upload.get_upload_content(upload_id)
    response = send_file(data, mimetype="application/tar+gzip")
    response.set_etag(headers.get('ETag'))
    return response

@blueprint.route('/<int:upload_id>/<path:public_file_path>/content', methods=['HEAD'])
@scoped(scopes.READ_UPLOAD)
def check_file_exists(upload_id: int, public_file_path: str) -> tuple:
    """
    Verify specified file exists.

    Returns an ``ETag`` header with the current source file checksum.
    """
    data, status_code, headers = upload.check_upload_file_content_exists(upload_id, public_file_path)

    return jsonify(data), status_code, headers


@blueprint.route('/<int:upload_id>/<path:public_file_path>/content', methods=['GET'])
@scoped(scopes.READ_UPLOAD)
def get_file_content(upload_id: int, public_file_path: str) -> tuple:
    """
    Return content of specified file.

    """

    data, status_code, headers = upload.get_upload_file_content(upload_id, public_file_path)

    response = send_file(data, mimetype="application/*")
    response.set_etag(headers.get('ETag'))
    return response


# Get logs

@blueprint.route('/<int:upload_id>/log', methods=['HEAD'])
@scoped(scopes.READ_UPLOAD_LOGS)
def check_upload_source_log_exists(upload_id: int) -> tuple:
    """
    Check that upload source log exists.

    Parameters
    ----------
    upload_id: int

    Returns
    -------
    Returns an ``ETag`` header with the current source package checksum.

    """
    data, status_code, headers = upload.check_upload_source_log_exists(upload_id)
    return jsonify(data), status_code, headers

@blueprint.route('/<int:upload_id>/log', methods=['GET'])
@scoped(scopes.READ_UPLOAD_LOGS)
def get_upload_source_log(upload_id: int) -> tuple:
    """
    Get the upload source log for specified upload workspace. This provides details of all
    upload/deletion activity on specified workspace.

    Parameters
    ----------
    upload_id : int

    Returns
    -------

    """
    data, status_code, headers = upload.get_upload_source_log(upload_id)
    response = send_file(data, mimetype="application/tar+gzip")
    response.set_etag(headers.get('ETag'))
    return response

@blueprint.route('/log', methods=['HEAD'])
@scoped(scopes.READ_UPLOAD_SERVICE_LOGS)
def check_upload_service_log_exists() -> tuple:
    """
    Check that upload source log exists.

    Returns
    -------
    Returns an ``ETag`` header with the current source package checksum.

    """
    data, status_code, headers = upload.check_upload_service_log_exists()
    return jsonify(data), status_code, headers

@blueprint.route('/log', methods=['GET'])
@scoped(scopes.READ_UPLOAD_SERVICE_LOGS)
def get_upload_service_log() -> tuple:
    """
    Return the top level file management service log that records high-level requests along with
    important errors/warnings. Details for specific upload workspace are found in workspace
    source log.

    Returns
    -------

    """
    data, status_code, headers = upload.get_upload_service_log()
    response = send_file(data, mimetype="application/tar+gzip")
    response.set_etag(headers.get('ETag'))
    return response

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
