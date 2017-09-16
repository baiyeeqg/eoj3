import json
import re
from os import path, remove

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse
from django.views import View
from django.views.generic import ListView, UpdateView, TemplateView
from django.views.generic.base import TemplateResponseMixin, ContextMixin
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from account.models import User
from account.permissions import is_admin_or_root
from polygon.base_views import PolygonBaseMixin, response_ok
from polygon.case import well_form_text
from polygon.forms import ProblemEditForm
from polygon.models import EditSession
from polygon.problem.session import init_session, pull_session, load_config, save_program_file, delete_program_file, \
    read_program_file, toggle_program_file_use
from polygon.problem.utils import sort_out_directory, normal_regex_check
from polygon.rejudge import rejudge_all_submission_on_problem
from problem.models import Problem, SpecialProgram
from problem.views import StatusList
from submission.models import Submission
from utils import random_string
from utils.download import respond_as_attachment
from utils.language import LANG_CHOICE
from utils.permission import is_problem_manager
from utils.upload import save_uploaded_file_to


class ProblemList(PolygonBaseMixin, ListView):
    template_name = 'polygon/problem/list.jinja2'
    context_object_name = 'problem_list'

    def get_queryset(self):
        if is_admin_or_root(self.request.user):
            return Problem.objects.all()
        else:
            return self.request.user.managing_problems.all()


class ProblemCreate(PolygonBaseMixin, View):

    def post(self, request):
        """
        It is actually "repository create"
        named "session create" for convenience
        """
        if request.method == 'POST':
            alias = request.POST['alias']
            if not normal_regex_check(alias):
                raise ValueError
            problem = Problem.objects.create(alias=alias)
            problem.title = 'Problem #%d' % problem.id
            problem.save(update_fields=['title'])
            problem.manager.add(request.user)
            return redirect(reverse('polygon:problem_edit', problem.pk))


class PolygonProblemMixin(TemplateResponseMixin, ContextMixin, PolygonBaseMixin):
    raise_exception = True

    def init_session_during_dispatch(self):
        pass

    def dispatch(self, request, *args, **kwargs):
        self.problem = get_object_or_404(Problem, pk=kwargs.get('pk'))
        self.init_session_during_dispatch()
        return super().dispatch(request, *args, **kwargs)

    def test_func(self):
        if not is_problem_manager(self.request.user, self.problem):
            return False
        return super(PolygonProblemMixin, self).test_func()

    def get_context_data(self, **kwargs):
        data = super(PolygonProblemMixin, self).get_context_data(**kwargs)
        data['problem'] = self.problem
        data['lang_choices'] = LANG_CHOICE
        data['builtin_program_choices'] = SpecialProgram.objects.filter(builtin=True).all()
        return data


class BaseSessionMixin(PolygonProblemMixin):

    def init_session_during_dispatch(self):
        if not (self.get_test_func())():
            # Manually check permission to make sure there is no redundant session created
            # Call super before update session does not work
            return self.handle_no_permission()
        try:
            self.session = self.problem.editsession_set.get(user=self.request.user)
        except EditSession.DoesNotExist:
            self.session = init_session(self.problem, self.request.user)
        self.config = load_config(self.session)

    def get_context_data(self, **kwargs):
        data = super(BaseSessionMixin, self).get_context_data(**kwargs)
        data['session'], data['config'] = self.session, self.config
        return data


class SessionPostMixin(BaseSessionMixin):
    redirect_view_name = None

    def dispatch(self, request, *args, **kwargs):
        try:
            return super().dispatch(request, *args, **kwargs)
        except Exception as e:
            messages.add_message(request, messages.ERROR, "%s: %s" % (e.__class__.__name__, str(e)))
        finally:
            if self.redirect_view_name:
                return redirect(reverse(self.redirect_view_name, kwargs=kwargs))
            # automatically raise exception here


class ProblemPreview(PolygonProblemMixin, TemplateView):
    template_name = 'polygon/problem/preview.jinja2'


class ProblemAccessManage(PolygonProblemMixin, View):
    def post(self, request, pk):
        upload_permission_set = set(map(int, filter(lambda x: x, request.POST['admin'].split(','))))
        for record in self.problem.managers.all():
            if record.id in upload_permission_set:
                upload_permission_set.remove(record.id)
            else:
                record.delete()
        for key in upload_permission_set:
            self.problem.managers.add(User.objects.get(pk=key))
        return redirect(reverse('polygon:problem_edit', kwargs={'pk': str(pk)}))


class ProblemEdit(PolygonProblemMixin, UpdateView):

    template_name = 'polygon/problem/edit.jinja2'
    form_class = ProblemEditForm
    queryset = Problem.objects.all()

    def get_object(self, queryset=None):
        return self.problem

    def get_context_data(self, **kwargs):
        data = super(ProblemEdit, self).get_context_data(**kwargs)
        data['admin_list'] = self.problem.managers.all()
        return data

    def get_success_url(self):
        return self.request.path


class ProblemStatus(PolygonProblemMixin, StatusList):
    template_name = 'polygon/problem/status.jinja2'

    def get_selected_from(self):
        return Submission.objects.filter(problem_id=self.problem.id)


class ProblemRejudge(PolygonProblemMixin, View):

    def post(self, request, *args, **kwargs):
        rejudge_all_submission_on_problem(self.problem)
        return redirect(reverse('polygon:problem_status', kwargs={'pk': self.problem.id}))


class ProblemPull(PolygonProblemMixin, APIView):

    def post(self, request, *args, **kwargs):
        try:
            session = EditSession.objects.get(problem=self.problem, user=request.user)
            pull_session(session)
        except EditSession.DoesNotExist:
            init_session(self.problem, request.user)
        messages.add_message(request, messages.SUCCESS, "Synchronization succeeded!")
        return Response()


class ProblemStaticFileList(PolygonProblemMixin, ListView):
    template_name = 'polygon/problem/files.jinja2'
    context_object_name = 'file_list'

    def get_queryset(self):
        r = sort_out_directory(path.join(settings.UPLOAD_DIR, str(self.problem.pk)))
        for dat in r:
            dat['url'] = '/upload/%d/%s' % (self.problem.id, dat['filename'])
            if re.search(r'(gif|jpg|jpeg|tiff|png)$', dat['filename'], re.IGNORECASE):
                dat['type'] = 'image'
            else:
                dat['type'] = 'regular'
        return r


class ProblemUploadStaticFile(PolygonProblemMixin, APIView):

    def post(self, request, *args, **kwargs):
        files = request.FILES.getlist('files[]')
        for file in files:
            save_uploaded_file_to(file, path.join(settings.UPLOAD_DIR, str(self.problem.pk)),
                                  filename=path.splitext(file.name)[0] + '.' + random_string(16),
                                  keep_extension=True)
        return redirect(reverse('polygon:problem_static_file_list', kwargs={'pk': self.problem.pk}))


class ProblemDeleteRegularFile(PolygonProblemMixin, APIView):

    def post(self, request, *args, **kwargs):
        filename = request.POST['filename']
        try:
            upload_base_dir = path.join(settings.UPLOAD_DIR, str(self.problem.pk))
            real_path = path.abspath(path.join(upload_base_dir, filename))
            if path.commonpath([real_path, upload_base_dir]) != upload_base_dir:
                return Response(status=status.HTTP_403_FORBIDDEN)
            remove(real_path)
        except OSError:
            return Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response()


class SessionProgramList(BaseSessionMixin, TemplateView):
    template_name = 'polygon/problem/program.jinja2'

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        data["program_list"] = program_list = []
        for filename, val in self.config["program"].items():
            program_list.append(dict(filename=filename))
            program_list[-1].update(val)
            program_list[-1]["lang_display"] = dict(LANG_CHOICE)[program_list[-1]["lang"]]
            program_list[-1]["code"] = read_program_file(self.session, filename)
            for sp_type in ['checker', 'validator', 'generator', 'interactor', 'model']:
                if self.config.get(sp_type) == filename:
                    program_list[-1].update(used=True)
        return data


class SessionCreateProgram(SessionPostMixin, View):
    redirect_view_name = 'polygon:session_program_list'

    def post(self, request, *args, **kwargs):
        filename, type, lang, code = request.POST['filename'], request.POST['type'], \
                                     request.POST['lang'], request.POST['code']
        save_program_file(self.session, filename, type, lang, code)


class SessionImportProgram(SessionPostMixin, View):
    redirect_view_name = 'polygon:session_program_list'

    def post(self, request, *args, **kwargs):
        type = request.POST['type']
        sp = SpecialProgram.objects.get(builtin=True, filename=type)
        save_program_file(self.session, sp.filename, sp.category, sp.lang, sp.code)


class SessionUpdateProgram(SessionPostMixin, View):
    redirect_view_name = 'polygon:session_program_list'

    def post(self, request, *args, **kwargs):
        raw_filename = request.POST['rawfilename']
        filename, type, lang, code = request.POST['filename'], request.POST['type'], \
                                     request.POST['lang'], request.POST['code']
        save_program_file(self.session, filename, type, lang, code, raw_filename)


class SessionDeleteProgram(SessionPostMixin, View):
    redirect_view_name = 'polygon:session_program_list'

    def post(self, request, *args, **kwargs):
        filename = request.POST['filename']
        delete_program_file(self.session, filename)


class SessionProgramUsedToggle(BaseSessionMixin, APIView):
    def post(self, request, pk):
        filename = request.POST['filename']
        toggle_program_file_use(self.session, filename)
        return Response()


class SessionEditUpdateAPI(BaseSessionMixin, View):

    def get(self, request, sid):
        data = self.get_context_data(sid=sid)
        app_data = data['config']
        app_data['config_update_time'] = get_config_update_time(self.session)
        app_data['problem_id'] = self.problem.id
        app_data['case_count'] = len(list(filter(lambda x: x.get('order'), app_data['case'].values())))
        app_data['pretest_count'] = len(list(filter(lambda x: x.get('pretest'), app_data['case'].values())))
        app_data['sample_count'] = len(list(filter(lambda x: x.get('sample'), app_data['case'].values())))
        app_data['volume_used'], app_data['volume_all'] = load_volume(self.session)
        app_data['regular_file_list'] = load_regular_file_list(self.session)
        for dat in app_data['regular_file_list']:
            dat['url'] = '/upload/%d/%s' % (self.problem.id, dat['filename'])
            if re.search(r'(gif|jpg|jpeg|tiff|png)$', dat['filename'], re.IGNORECASE):
                dat['type'] = 'image'
            else:
                dat['type'] = 'regular'
        app_data['program_special_identifier'] = ['checker', 'validator', 'generator', 'interactor', 'model']
        app_data['program_file_list'] = load_program_file_list(self.session)
        language_choice_dict = dict(LANG_CHOICE)
        for dat in app_data['program_file_list']:
            extra_data = app_data['program'].get(dat['filename'])
            if extra_data:
                dat.update(extra_data)
                for identifier in app_data['program_special_identifier']:
                    if dat['filename'] == app_data.get(identifier):
                        dat['used'] = identifier
                dat['lang_display'] = language_choice_dict[dat['lang']]
            else:
                dat['remove_mark'] = True
        app_data['program_file_list'] = list(filter(lambda x: not x.get('remove_mark'), app_data['program_file_list']))
        for key, val in app_data['case'].items():
            val.update(get_case_metadata(self.session, key))
        # print(json.dumps(app_data, sort_keys=True, indent=4))
        return HttpResponse(json.dumps(app_data))


class BaseSessionPostMixin:
    pass

class SessionCreateCaseManually(BaseSessionPostMixin, View):

    def post(self, request, sid):
        input = request.POST['input']
        output = request.POST['output']
        well_form = request.POST.get("wellForm") == "on"
        if well_form:
            input, output = well_form_text(input), well_form_text(output)
        if not input:
            raise ValueError('Input file cannot be empty')
        save_case(self.session, input.encode(), output.encode(), well_form=well_form)
        return response_ok()


class SessionUpdateOrders(BaseSessionPostMixin, View):

    def post(self, request, sid):
        case = json.loads(request.POST['case'])
        unused = json.loads(request.POST['unused'])
        conclusion = dict()
        for order, k in enumerate(case, start=1):
            conclusion[k['fingerprint']] = order
        for k in unused:
            conclusion[k['fingerprint']] = 0
        reorder_case(self.session, conclusion)
        return response_ok()


class SessionPreviewCase(BaseSessionMixin, View):

    def get(self, request, sid):
        fingerprint = request.GET['case']
        return HttpResponse(json.dumps(preview_case(self.session, fingerprint)))


class SessionUploadCase(BaseSessionPostMixin, View):

    def post(self, request, sid):
        file = request.FILES['file']
        file_directory = '/tmp'
        file_path = save_uploaded_file_to(file, file_directory, filename=random_string(), keep_extension=True)
        process_uploaded_case(self.session, file_path)
        remove(file_path)
        return response_ok()


class SessionReformCase(BaseSessionPostMixin, View):

    def post(self, request, sid):
        case = request.POST['fingerprint']
        inputOnly = request.POST.get('inputOnly') == 'on'
        reform_case(self.session, case, only_input=inputOnly)
        return response_ok()


class SessionUpdateCasePoint(BaseSessionPostMixin, View):

    def post(self, request, sid):
        point = request.POST['point']
        case = request.POST['fingerprint']
        readjust_case_point(self.session, case, int(point))
        return response_ok()


class SessionValidateCase(BaseSessionPostMixin, View):

    def post(self, request, sid):
        case = request.POST['fingerprint']
        validator = request.POST['program']
        return response_ok(run_id=validate_case("Validate a case", self.session, validator, case))


class SessionRunCaseOutput(BaseSessionPostMixin, View):

    def post(self, request, sid):
        case = request.POST['fingerprint']
        model = request.POST['program']
        return response_ok(run_id=get_case_output("Run case output", self.session, model, case))


class SessionCheckCaseOutput(BaseSessionPostMixin, View):

    def post(self, request, sid):
        case = request.POST['fingerprint']
        submission = request.POST['program']
        checker = request.POST['checker']
        return response_ok(run_id=check_case("Check a case", self.session, submission, checker, case))


class SessionValidateAllCase(BaseSessionPostMixin, View):

    def post(self, request, sid):
        validator = request.POST['program']
        return response_ok(run_id=validate_case("Validate all cases", self.session, validator))


class SessionRunAllCaseOutput(BaseSessionPostMixin, View):

    def post(self, request, sid):
        model = request.POST['program']
        return response_ok(run_id=get_case_output("Run all case outputs", self.session, model))


class SessionCheckAllCaseOutput(BaseSessionPostMixin, View):

    def post(self, request, sid):
        submission = request.POST['program']
        checker = request.POST['checker']
        return response_ok(run_id=check_case("Check all cases", self.session, submission, checker))


class SessionDeleteCase(BaseSessionPostMixin, View):

    def post(self, request, sid):
        case = request.POST['fingerprint']
        delete_case(self.session, case)
        return response_ok()


class SessionDownloadInput(BaseSessionMixin, View):

    def get(self, request, sid):
        case = request.GET['fingerprint']
        input, _ = get_test_file_path(self.session, case)
        return respond_as_attachment(request, input, case + '.in')


class SessionDownloadOutput(BaseSessionMixin, View):

    def get(self, request, sid):
        case = request.GET['fingerprint']
        _, output = get_test_file_path(self.session, case)
        return respond_as_attachment(request, output, case + '.in')


class SessionGenerateInput(BaseSessionPostMixin, View):

    def post(self, request, sid):
        generator = request.POST['generator']
        raw_param = request.POST['param']
        return response_ok(run_id=generate_input('Generate cases', self.session, generator, raw_param))


class SessionAddCaseFromStress(BaseSessionPostMixin, View):

    def post(self, request, sid):
        generator = request.POST['generator']
        raw_param = request.POST['param']
        submission = request.POST['submission']
        time = int(request.POST['time']) * 60
        if time < 60 or time > 300:
            raise ValueError('Time not in range')
        return response_ok(run_id=stress('Stress test', self.session, generator, submission, raw_param, time))


class SessionReformAllCase(BaseSessionPostMixin, View):

    def post(self, request, sid):
        inputOnly = request.POST.get('inputOnly') == 'on'
        config = load_config(self.session)
        for case in list(config['case'].keys()):
            reform_case(self.session, case, only_input=inputOnly)
        return response_ok()


class SessionTogglePretestCase(BaseSessionPostMixin, View):

    def post(self, request, sid):
        case = request.POST['fingerprint']
        config = load_config(self.session)
        config['case'][case]['pretest'] = not bool(config['case'][case].get('pretest'))
        dump_config(self.session, config)
        return response_ok()


class SessionToggleSampleCase(BaseSessionPostMixin, View):

    def post(self, request, sid):
        case = request.POST['fingerprint']
        config = load_config(self.session)
        config['case'][case]['sample'] = not bool(config['case'][case].get('sample'))
        dump_config(self.session, config)
        return response_ok()


class SessionPullHotReload(BaseSessionPostMixin, View):

    def post(self, request, sid):
        pull_session(self.session)
        return response_ok()


class SessionPush(BaseSessionPostMixin, View):

    def post(self, request, sid):
        push_session(self.session)
        return response_ok()
