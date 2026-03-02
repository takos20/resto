# sync/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from globals.pagination import CustomPagination
from hospital.helpers import SyncPermission
from sync.filters import SyncConfigFilter, SyncLogFilter
from sync.models import SyncConfig, SyncLog
from .sync_service import SyncService
from .serializers import SyncLogSerializer, SyncConfigSerializer
from rest_framework.permissions import AllowAny, IsAuthenticated, DjangoModelPermissions
from rest_framework.renderers import JSONRenderer
from django_filters import rest_framework as filters

class SyncViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend]

    @action(detail=False, methods=['post'], url_path='upload')
    def upload(self, request):
        hospital_id = request.data.get('hospital_id')
        force = request.data.get('force', False)

        if not hospital_id:
            return Response({'error': 'hospital_id requis'}, status=400)

        try:
            config = SyncConfig.objects.get(hospital_id=hospital_id)
            service = SyncService(hospital_id=hospital_id, config=config)
            results = service.upload_changes(force=force)

            return Response({'message': 'Upload terminé', 'results': results})

        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=False, methods=['post'], url_path='download')
    def download(self, request):
        hospital_id = request.data.get('hospital_id')
        force = request.data.get('force', False)

        if not hospital_id:
            return Response({'error': 'hospital_id requis'}, status=400)

        try:
            config = SyncConfig.objects.get(hospital_id=hospital_id)
            service = SyncService(hospital_id=hospital_id, config=config)
            results = service.download_changes(force=force)

            return Response({'message': 'Download terminé', 'results': results})

        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=False, methods=['post'], url_path='full_sync')
    def full_sync(self, request):
        hospital_id = request.data.get('hospital_id')

        if not hospital_id:
            return Response({'error': 'hospital_id requis'}, status=400)

        try:
            config = SyncConfig.objects.get(hospital_id=hospital_id)
            service = SyncService(hospital_id=hospital_id, config=config)

            upload_results = service.upload_changes(force=True)
            download_results = service.download_changes(force=True)

            return Response({
                'message': 'Sync complète terminée',
                'upload': upload_results,
                'download': download_results,
                'status': service.get_sync_status()
            })

        except Exception as e:
            return Response({'error': str(e)}, status=500)
class SyncLogViewSet(viewsets.ViewSet):
    queryset = SyncLog.objects.all()
    serializer_class = SyncLogSerializer
    renderer_classes = [JSONRenderer]
    permission_classes = (IsAuthenticated, DjangoModelPermissions)
    pagination_class = CustomPagination
    filterset_class = SyncLogFilter
    filter_backends = (filters.DjangoFilterBackend,)