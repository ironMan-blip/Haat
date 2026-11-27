"""AI apps sign in to a buyer's account over OAuth 2.1 (django-oauth-toolkit does the protocol).

The app registers itself, then opens `authorize` in the buyer's browser. That hands the request to the React
/connect page, which sends the buyer through the normal login if needed and asks them to allow the app;
`Connect` checks the request again and answers. The app swaps the code for tokens at DOT's `token` view."""
from urllib.parse import urlsplit

from django.http import HttpResponseRedirect
from django.urls import path
from oauth2_provider import urls as dot_urls
from oauth2_provider import views as dot
from oauth2_provider.exceptions import OAuthToolkitError
from oauth2_provider.models import get_application_model
from oauth2_provider.oauth2_validators import is_valid_resource_uri
from oauth2_provider.views.mixins import OAuthLibMixin
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


def authorize(request):
    # The page is the React app's; the query is the app's request, passed on untouched, and Connect checks it.
    query = request.META.get("QUERY_STRING", "")
    return HttpResponseRedirect(f"/connect?{query}" if query else "/connect")


class Connect(OAuthLibMixin, APIView):
    """GET: what the /connect page shows about the app asking. POST {"allow": true|false}: the signed-in buyer's
    answer. Both read the app's request from the query string and answer {"redirect": url} once the browser
    should go back to the app (with a code, or with an error the app understands)."""
    permission_classes = [IsAuthenticated]

    def authorization(self, request):
        """The app's request, checked by oauthlib. A bad app or return address gets an error here, never a
        redirect, so this page can't send a buyer to a site the app didn't register."""
        try:
            scopes, credentials = self.validate_authorization_request(request._request)
        except OAuthToolkitError as error:
            redirect, response = self.error_response(error)
            if redirect:
                return None, None, Response({"redirect": response["url"]})
            raise ValidationError(error.oauthlib_error.description or "This app's sign-in request is not valid.")
        resources = request.query_params.getlist("resource")  # RFC 8707; oauthlib leaves it to DOT's own view
        if not all(is_valid_resource_uri(r) for r in resources):
            raise ValidationError("This app asked for an address that is not valid.")
        if resources:
            credentials["resource"] = resources
        return scopes, credentials, None

    def get(self, request):
        scopes, credentials, done = self.authorization(request)
        if done:
            return done
        app = get_application_model().objects.get(client_id=credentials["client_id"])
        name = app.name or "An AI app"
        return Response({
            "title": f"Connect {name} to your Haat account?",
            "lead": f"{name} wants to browse the shop, use your cart and place cash-on-delivery orders as "
                    f"{request.user.username}.",
            # A look-alike app can copy a name, not where the buyer lands after allowing it.
            "returns_to": f"After you answer, you go back to {urlsplit(credentials['redirect_uri']).hostname}.",
        })

    def post(self, request):
        scopes, credentials, done = self.authorization(request)
        if done:
            return done
        try:
            uri, _, _, _ = self.create_authorization_response(
                request._request, " ".join(scopes), credentials, allow=request.data.get("allow") is True)
        except OAuthToolkitError as error:  # "Don't allow" lands here too, as access_denied
            redirect, response = self.error_response(error)
            if not redirect:
                raise ValidationError(error.oauthlib_error.description or "This app's sign-in request is not valid.")
            uri = response["url"]
        return Response({"redirect": uri})


# The URL names are DOT's: its metadata view finds the endpoints by them.
urlpatterns = [
    path("authorize/", authorize, name="authorize"),
    path("connect/", Connect.as_view(), name="connect"),
    path("token/", dot.TokenView.as_view(), name="token"),
    path("revoke_token/", dot.RevokeTokenView.as_view(), name="revoke-token"),
    *dot_urls.dcr_urlpatterns,  # register/: apps register themselves (RFC 7591)
]
