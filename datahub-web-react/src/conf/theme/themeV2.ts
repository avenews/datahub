import light from '@conf/theme/colorThemes/light';
import { Theme } from '@conf/theme/types';

const themeV2: Theme = {
    id: 'themeV2',
    colors: light,
    styles: {
        'primary-color': '#37C1CE',
        'primary-color-dark': '#2BA8B4',
        'primary-color-light': '#DFF2F3',
        'layout-header-color': '#152C5B',
        'body-background': '#F5F8FB',
        'border-color-base': '#DEE9EC',
        'homepage-background-upper-fade': '#F5F8FB',
        'homepage-background-lower-fade': '#FFFFFF',
        'homepage-text-color': '#152C5B',
        'box-shadow': '0px 0px 30px 0px rgb(239 239 239)',
        'box-shadow-hover': '0px 1px 0px 0.5px rgb(239 239 239)',
        'box-shadow-navbar-redesign': '0 0 6px 0px rgba(93, 102, 139, 0.20)',
        'border-radius-navbar-redesign': '12px',
        'highlight-color': '#DFF2F3',
        'highlight-border-color': '#37C1CE80',
    },
    assets: {
        logoUrl: 'assets/logo.png',
    },
    content: {
        title: 'Avenews DataHub',
        search: {
            searchbarMessage: 'Find tables, dashboards, people, and more',
        },
        menu: {
            items: [
                {
                    label: 'DataHub Project',
                    path: 'https://docs.datahub.com',
                    shouldOpenInNewTab: true,
                    description: 'Explore DataHub Project website',
                },
                {
                    label: 'DataHub GitHub',
                    path: 'https://github.com/linkedin/datahub',
                    shouldOpenInNewTab: true,
                },
            ],
        },
    },
};

export default themeV2;
