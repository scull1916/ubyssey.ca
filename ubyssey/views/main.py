from datetime import datetime
import random
import json

from django.shortcuts import render_to_response
from django.http import HttpResponse, Http404
from django.template import loader
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.urlresolvers import reverse
from django.contrib.staticfiles.templatetags.staticfiles import static
from django_user_agents.utils import get_user_agent

from dispatch.models import Article, Section, Subsection, Topic, Person, Podcast, PodcastEpisode

import ubyssey
import ubyssey.cron
from ubyssey.helpers import ArticleHelper, PageHelper, SubsectionHelper, PodcastHelper

def parse_int_or_none(maybe_int):
    try:
        return int(maybe_int)
    except (TypeError, ValueError):
        return None


class UbysseyTheme(object):

    SITE_TITLE = 'The Ubyssey'
    SITE_URL = settings.BASE_URL

    def home(self, request):
        frontpage = ArticleHelper.get_frontpage(
            sections=('news', 'culture', 'opinion', 'sports', 'features', 'science'),
            max_days=7
        )

        trending_article = ArticleHelper.get_trending()

        elections = ArticleHelper.get_topic('AMS Elections').order_by('-published_at')

        frontpage_ids = [int(a.id) for a in frontpage[:2]]

        sections = ArticleHelper.get_frontpage_sections(exclude=frontpage_ids)

        try:
            podcast = Podcast.objects.all()[:1].get()
            podcast_url = PodcastHelper.get_podcast_url(podcast.id)
        except:
            podcast = None
            podcast_url = None

        episode_list = None    
        episode_urls = []
        episodes = None

        if (podcast):
            try:
                episode_list = PodcastEpisode.objects.filter(podcast_id=podcast.id).order_by('-published_at')
            except: 
                episode_list = None
            if episode_list:    
                for episode in episode_list:
                    episode_urls += [PodcastHelper.get_podcast_episode_url(episode.podcast_id, episode.id)]
            
            episodes = zip(episode_list, episode_urls)

        breaking = ArticleHelper.get_breaking_news().first()

        # determine if user is viewing from mobile
        user_agent = get_user_agent(request)

        try:
            articles = {
                'primary': frontpage[0],
                'secondary': frontpage[1],
                'thumbs': frontpage[2:4],
                'bullets': frontpage[4:6],
                # Get random trending article
                'trending': trending_article,
                'breaking': breaking
             }
        except IndexError:
            raise Exception('Not enough articles to populate the frontpage!')

        popular = ArticleHelper.get_popular()[:5]

        blog = ArticleHelper.get_frontpage(section='blog', limit=5)

        title = '%s - UBC\'s official student newspaper' % self.SITE_TITLE

        podcast_obj = None
        if podcast and episode_list:
            podcast_obj = { 'title': podcast.title, 'url': podcast_url, 'episodes': {'first': episodes[0], 'rest': episodes[1:]} }

        context = {
            'title': title,
            'meta': {
                'title': title,
                'description': 'Weekly student newspaper of the University of British Columbia.',
                'url': self.SITE_URL
            },
            'title': '%s - UBC\'s official student newspaper' % self.SITE_TITLE,
            'articles': articles,
            'sections': sections,
            'podcast': podcast_obj,
            'popular': popular,
            'breaking': breaking,
            'blog': blog,
            'day_of_week': datetime.now().weekday(),
            'is_mobile': user_agent.is_mobile
        }

        return render(request, 'homepage/base.html', context)

    def article(self, request, section=None, slug=None):
        try:
            article = ArticleHelper.get_article(request, slug)
        except:
            raise Http404('Article could not be found.')

        article.add_view()

        breaking = ArticleHelper.get_breaking_news().exclude(id=article.id).first()

        # determine if user is viewing from mobile
        article_type = 'desktop'
        user_agent = get_user_agent(request)
        if user_agent.is_mobile:
            article_type = 'mobile'


        if article.template == 'timeline':
            timeline_tag = article.tags.filter(name__icontains='timeline-')
            timelineArticles = Article.objects.filter(tags__in=timeline_tag, is_published=True)
            temp = list(timelineArticles.values('parent_id', 'template_data', 'slug', 'headline', 'featured_image'))
            try:
                temp = sorted(temp, key=lambda article: json.loads(article['template_data'])['timeline_date'])
            except:
                pass
            for i, a in enumerate(timelineArticles) :
                try:
                    temp[i]['featured_image'] = a.featured_image.image.get_thumbnail_url()
                except:
                    temp[i]['featured_image'] = None
            article.timeline_articles = json.dumps(temp)
            article.timeline_title = list(timeline_tag)[0].name.replace('timeline-', '').replace('-', ' ')


        ref = request.GET.get('ref', None)
        dur = request.GET.get('dur', None)

        if not ArticleHelper.is_explicit(article):
            article.content = ArticleHelper.insert_ads(article.content, article_type)

        popular = ArticleHelper.get_popular()[:5]

        context = {
            'title': '%s - %s' % (article.headline, self.SITE_TITLE),
            'meta': ArticleHelper.get_meta(article),
            'article': article,
            'reading_list': ArticleHelper.get_reading_list(article, ref=ref, dur=dur),
            # 'suggested': lambda: ArticleHelper.get_random_articles(2, section, exclude=article.id),
            'base_template': 'base.html',
            'popular': popular,
            'reading_time': ArticleHelper.get_reading_time(article),
            'explicit': ArticleHelper.is_explicit(article),
            'breaking': breaking,
        }

        template = article.get_template_path()
        t = loader.select_template(['%s/%s' % (article.section.slug, template), template, 'article/default.html'])
        return HttpResponse(t.render(context))

    def article_ajax(self, request, pk=None):
        article = Article.objects.get(parent_id=pk, is_published=True)
        authors_json = [a.person.full_name for a in article.authors.all()]

        context = {
            'article': article,
            'authors_json': authors_json,
            'base_template': 'blank.html'
        }

        try:
            featured_image = article.featured_image.image.get_thumbnail_url()
        except:
            featured_image = None

        data = {
            'id': article.parent_id,
            'headline': article.headline,
            'url': article.get_absolute_url(),
            'authors': authors_json,
            'published_at': str(article.published_at),
            'featured_image': featured_image
        }

        return HttpResponse(json.dumps(data), content_type='application/json')

    def page(self, request, slug=None):
        try:
            page = PageHelper.get_page(request, slug)
        except:
            return self.subsection(request, slug)

        page.add_view()

        try:
            image = page.featured_image.image.get_medium_url()
        except:
            image = None

        context = {
            'meta': {
                'title': page.title,
                'image': image,
                'url': settings.BASE_URL[:-1] + reverse('page', args=[page.slug]),
                'description': page.snippet if page.snippet else ''
            },
            'page': page
        }

        if page.get_template() != 'article/default.html':
            templates = [page.get_template(), 'page/base.html']
        else:
            templates = ['page/base.html']

        t = loader.select_template(templates)
        return HttpResponse(t.render(context))

    def elections(self, request):
        articles = ArticleHelper.get_topic('AMS Elections').order_by('-published_at')

        topic = Topic.objects.filter(name='AMS Elections')[0]

        context = {
            'meta': {
                'title': '2017 AMS Elections'
            },
            'section': {
                'name': '2017 AMS Elections',
                'slug': 'elections',
                'id': topic.id
            },
            'type': 'topic',
            'articles': {
                'first': articles[0],
                'rest': articles[1:9]
            }
        }

        return render(request, 'section.html', context)

    def section(self, request, slug=None):
        try:
            section = Section.objects.get(slug=slug)
        except:
            return self.page(request, slug)

        order = request.GET.get('order', 'newest')

        if order == 'newest':
            order_by = '-published_at'
        else:
            order_by = 'published_at'

        query = request.GET.get('q', False)

        featured_articles = Article.objects.filter(section=section, is_published=True).order_by('-published_at')

        subsections = SubsectionHelper.get_subsections(section)

        featured_subsection = None
        featured_subsection_articles = None
        
        if subsections:
            featured_subsection = subsections[0]
            featured_subsection_articles = SubsectionHelper.get_featured_subsection_articles(featured_subsection, featured_articles)

        article_list = Article.objects.filter(section=section, is_published=True).order_by(order_by)

        if query:
            article_list = article_list.filter(headline__icontains=query)

        paginator = Paginator(article_list, 15) # Show 15 articles per page

        page = request.GET.get('page')

        try:
            articles = paginator.page(page)
        except PageNotAnInteger:
            # If page is not an integer, deliver first page.
            articles = paginator.page(1)
        except EmptyPage:
            # If page is out of range (e.g. 9999), deliver last page of results.
            articles = paginator.page(paginator.num_pages)

        context = {
            'meta': {
                'title': section.name,
            },
            'section': section,
            'subsections': subsections,
            'featured_subsection': {
                'subsection': featured_subsection,
                'articles' : featured_subsection_articles
            },
            'type': 'section',
            'featured_articles': {
                'first': featured_articles[0],
                'rest': featured_articles[1:4]
            },
            'articles': articles,
            'order': order,
            'q': query
        }

        t = loader.select_template(['%s/%s' % (section.slug, 'section.html'), 'section.html'])
        return HttpResponse(t.render(context))

    def subsection(self, request, slug=None):
        try:
            subsection = Subsection.objects.get(slug=slug, is_active=True)
        except:
            raise Http404('Page could not be found')

        if not subsection.get_published_articles().exists():
            raise Http404('Page could not be found')

        order = request.GET.get('order', 'newest')

        if order == 'newest':
            order_by = '-published_at'
        else:
            order_by = 'published_at'

        query = request.GET.get('q', False)

        featured_articles = Article.objects.filter(subsection=subsection, is_published=True).order_by('-published_at')

        article_list = Article.objects.filter(subsection=subsection, is_published=True).order_by(order_by)

        if query:
            article_list = article_list.filter(headline__icontains=query)

        paginator = Paginator(article_list, 15) # Show 15 articles per page

        page = request.GET.get('page')

        try:
            articles = paginator.page(page)
        except PageNotAnInteger:
            # If page is not an integer, deliver first page.
            articles = paginator.page(1)
        except EmptyPage:
            # If page is out of range, deliver last page of results.
            articles = paginator.page(paginator.num_pages)

        context = {
            'meta': {
                'title': subsection.name
            },
            'subsection': subsection,
            'type': 'subsection',
            'featured_articles': {
                'first': featured_articles[0],
                'rest': featured_articles[1:4]
            },
            'articles': articles,
            'order': order,
            'q': query
        }

        t = loader.select_template(['%s/%s' % (subsection.slug, 'subsection.html'), 'subsection.html'])
        return HttpResponse(t.render(context))

    def author(self, request, slug=None):
        try:
            person = Person.objects.get(slug=slug)
        except:
            raise Http404('Author could not be found.')

        order = request.GET.get('order', 'newest')

        if order == 'newest':
            order_by = '-published_at'
        else:
            order_by = 'published_at'

        query = request.GET.get('q', False)

        article_list = Article.objects.filter(authors__person=person, is_published=True).order_by(order_by)

        if query:
            article_list = article_list.filter(headline__icontains=query)

        paginator = Paginator(article_list, 15) # Show 15 articles per page

        page = request.GET.get('page')

        try:
            articles = paginator.page(page)
        except PageNotAnInteger:
            # If page is not an integer, deliver first page.
            articles = paginator.page(1)
        except EmptyPage:
            # If page is out of range (e.g. 9999), deliver last page of results.
            articles = paginator.page(paginator.num_pages)

        context = {
            'meta': {
                'title': person.full_name,
                'image': person.get_image_url if person.image is not None else None,
            },
            'person': person,
            'articles': articles,
            'order': order,
            'q': query
        }

        return render(request, 'author.html', context)

    def archive(self, request):
        years = ArticleHelper.get_years()

        sections = Section.objects.all()

        order = request.GET.get('order')
        if order != 'oldest':
            order = 'newest'

        filters = []

        if order == 'oldest':
            filters.append('order=%s' % order)

        order_by = '-published_at' if order == 'newest' else 'published_at'

        context = {
            'sections': sections,
            'years': years,
            'order': order
        }

        query = request.GET.get('q', '').strip() or None
        section_id = parse_int_or_none(request.GET.get('section_id'))

        year = parse_int_or_none(request.GET.get('year'))

        article_list = Article.objects.filter(is_published=True).order_by(order_by)

        if year:
            context['year'] = year
            article_list = article_list.filter(published_at__icontains=str(year))
            filters.append('year=%s' % year)

        if query:
            article_list = article_list.filter(headline__icontains=query)
            context['q'] = query
            filters.append('q=%s' % query)

        if section_id:
            article_list = article_list.filter(section=section_id)
            context['section_id'] = section_id
            context['section_name'] = Section.objects.get(id=section_id)
            filters.append('section_id=%s' % section_id)

        if filters:
            query_string = '?' + '&'.join(filters)
        else:
            query_string = ''

        paginator = Paginator(article_list, 15) # Show 15 articles per page
        page = request.GET.get('page')

        try:
            articles = paginator.page(page)
        except PageNotAnInteger:
            articles = paginator.page(1)
        except EmptyPage:
            articles = paginator.page(paginator.num_pages)

        meta = {
            'title': 'Archive'
        }

        context['articles'] = articles
        context['count'] = paginator.count
        context['meta'] = meta
        context['query_string'] = query_string

        return render(request, 'archive.html', context)

    def search(self, request):
        return redirect(self.archive)

    def topic(self, request, pk=None):
        try:
            topic = Topic.objects.get(id=pk)
        except Topic.DoesNotExist:
            raise Http404('Topic does not exist.')

        articles = Article.objects.filter(topic=topic, is_published=True).order_by('-published_at')

        context = {
            'meta': {
                'title': topic.name
            },
            'section': topic,
            'type': 'topic',
            'articles': {
                'first': articles[0] if articles else None,
                'rest': articles[1:9]
            }
        }

        return render(request, 'section.html', context)

    def newsletter(self, request):
        return render(request, 'objects/newsletter.html', {})

    def centennial(self, request):
        return render(request, 'centennial.html', {})

    def notification(self, request):
        return render(request, 'notification_signup.html', {})

    def podcast(self, request, slug=None):
        try:
            podcast = Podcast.objects.all()[:1].get()
        except:
            raise Http404('We could not find the podcast')

        episode_list = PodcastEpisode.objects.filter(podcast_id=podcast.id).order_by('-published_at')

        episode_urls = []
        for episode in episode_list:
            episode_urls += [PodcastHelper.get_podcast_episode_url(episode.podcast_id, episode.id)]

        episodes = zip(episode_list, episode_urls)

        url = PodcastHelper.get_podcast_url(id=podcast.id)
        context = {
            'podcast': podcast,
            'url': url,
            'episodes': episodes
        }

        return render(request, 'podcasts/podcast.html', context)
        
