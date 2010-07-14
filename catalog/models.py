# -*- coding: utf-8 -*-
from catalog import settings as catalog_settings
from django.contrib.contenttypes import generic
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.signals import post_save
from catalog.admin.utils import get_connected_models
from django.db.models import permalink
from django.core.urlresolvers import reverse

if catalog_settings.CATALOG_MPTT:
    import mptt
else:
    from catalog import dummy_mptt as mptt


class Base(models.Model):
    class Meta:
        abstract = True

    tree = generic.GenericRelation('TreeItem')
    tree_id = models.IntegerField(editable=False, null=True)
    exclude_children = []
    parent = None

    def save(self, *args, **kwds):
        save_tree_id = kwds.pop('save_tree_id', False)
        if save_tree_id:
            self.tree_id = self.tree.get().id
        return super(Base, self).save(*args, **kwds)
    save.alters_data = True

    def delete(self, *args, **kwds):
        super(Base, self).delete(*args, **kwds)
    delete.alters_data = True

    def get_absolute_url(self):
        return self.tree.get().get_absolute_url()

class TreeItemManager(models.Manager):

    def json(self, treeitem_id):
        '''Returns treeitem by it's id, if "root" given returns None'''
        if treeitem_id == 'root':
            return None
        else:
            return TreeItem.objects.get(id=treeitem_id)

    def json_children(self, parent, process_queryset=True):
        '''
        Returns children treeitems by their parent id.
        If 'root' given returns root treeitems
        '''
        if parent == 'root':
            parent = None
        q_object = models.Q(parent=parent)
        if process_queryset:
            return self.get_query_set().filter(q_object)
        else:
            return q_object

    def linked(self, parent, process_queryset=True):
        from catalog.admin.ext import catalog_admin_site

        # to make empty queryset
        q_object = models.Q(object_id= -1)
        if parent == 'root':
            if process_queryset:
                return self.get_empty_query_set()
            else:
                return q_object

        treeitem = TreeItem.objects.get(id=parent)

        for key, m2m in catalog_admin_site._m2ms.iteritems():
            # For each registered m2m get linked objects
            if type(treeitem.content_object) is m2m['base_model']:
                related_manager = getattr(treeitem.content_object, m2m['fk_attr'])
                linked_ids = related_manager.values_list('id', flat=True)
                linked_ct = ContentType.objects.get_for_model(m2m['rel_model'])
                q_object |= models.Q(content_type=linked_ct, object_id__in=linked_ids)

        if process_queryset:
            return self.get_query_set().filter(q_object)
        else:
            return q_object

    def all_children(self, parent):
        '''
        Be careful, this method may hit database!
        '''
        children_q_object = self.json_children(parent, process_queryset=False)
        linked_q_object = self.linked(parent, process_queryset=False)
        return TreeItem.objects.filter(children_q_object | linked_q_object)

class TreeItem(models.Model):
    class Meta:
        verbose_name = u'Элемент каталога'
        verbose_name_plural = u'Элементы каталога'
        if catalog_settings.CATALOG_MPTT:
            ordering = ['tree_id', 'lft']
        else:
            ordering = ['order']

    parent = models.ForeignKey('self', related_name='children',
        verbose_name=u'Родительский', null=True, blank=True, editable=False)

    content_type = models.ForeignKey(ContentType)
    object_id = models.PositiveIntegerField()
    content_object = generic.GenericForeignKey('content_type', 'object_id')

    if not catalog_settings.CATALOG_MPTT:
        order = models.IntegerField(null=True, default=0)

    objects = TreeItemManager()

    def is_first_root(self):
        """Return true if the self is the first root object."""
        if self.parent:
            return False
        try:
            return TreeItem.objects.all()[0].id == self.id
        except IndexError:
            return False

    def get_absolute_url(self):
        if catalog_settings.CATALOG_ROOT_PAGE and self.is_first_root():
            return reverse('catalog_root_page')
        if catalog_settings.CATALOG_URL_SCHEME == 'id':
            return reverse('tree', kwargs={
                'item_id': self.id,
            })
        if catalog_settings.CATALOG_URL_SCHEME == 'combo':
            return reverse('tree', kwargs={
                'item_id': self.id,
                'slug': self.slug(),
            })
        elif catalog_settings.CATALOG_URL_SCHEME == 'slug':
            return reverse('tree', kwargs={
                'slug': self.slug(),
                'model': self.content_type.model,
            })

    def delete(self, *args, **kwds):
        self.content_object.delete()
        super(TreeItem, self).delete(*args, **kwds)
    delete.alters_data = True

    def save(self, *args, **kwds):
        if not catalog_settings.CATALOG_MPTT:
            if self.order is None:
                max_order = TreeItem.objects.json_children(self.parent).latest('order').order
                self.order = max_order + 1
        return super(TreeItem, self).save(*args, **kwds)
    save.alters_data = True

    def get_level(self):
        ''' need to override this, because when we turn mptt off,
            level attr will clash with level method
        '''
        return self.level

    def all_children(self):
        return TreeItem.objects.all_children(self.id)

    def all_siblings(self):
        if self.parent:
            return TreeItem.objects.all_children(self.parent.id)
        else:
            return TreeItem.objects.all_children('root')

    def slug(self):
        try:
            return self.content_object.slug
        except:
            return u'slug'

    def __unicode__(self):
        return unicode(self.content_object)

try:
    mptt.register(TreeItem, tree_manager_attr='tree_objects')
except mptt.AlreadyRegistered:
    pass



# HACK: import models by their names for convenient usage
for model_name, admin_name in catalog_settings.CATALOG_CONNECTED_MODELS:
    module, model = model_name.rsplit('.', 1)
    exec('from %s import %s' % (module, model))

def filtered_children_factory(model_name):
    def func(self):
        return self.children.filter(content_type__model=model_name)
    return func

def insert_in_tree(sender, instance, **kwrgs):
    '''
    Insert newly created object in catalog tree.
    If no parent provided, insert object in tree root 
    '''
    # to avoid recursion save, process only for new instances
    created = kwrgs.pop('created', False)

    if created:
        parent = getattr(instance, 'parent')
        parent_tree_item = TreeItem.objects.json(parent)
        tree_item = TreeItem(parent=parent_tree_item, content_object=instance)
        tree_item.save()
        instance.save(save_tree_id=True)

for model_cls, admin_cls in get_connected_models():
    # for each connected model:
    model_name = model_cls.__name__.lower()
    # set hack attribute, so you can use it in templates like this:
    #    Children item list: {{ treeitem.children_item.all }}
    #    Children section list: {{ treeitem.children_section.all }}
    setattr(TreeItem, 'children_%s' % model_name, filtered_children_factory(model_name))

    # connect automatic TreeItem creation for catalog models
    post_save.connect(insert_in_tree, model_cls)
