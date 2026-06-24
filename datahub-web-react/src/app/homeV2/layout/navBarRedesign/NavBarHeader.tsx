import React from 'react';
import { Link } from 'react-router-dom';
import styled from 'styled-components';

import { useNavBarContext } from '@app/homeV2/layout/navBarRedesign/NavBarContext';
import NavBarToggler from '@app/homeV2/layout/navBarRedesign/NavBarToggler';
import { useShowHomePageRedesign } from '@app/homeV3/context/hooks/useShowHomePageRedesign';
import { useIsHomePage } from '@app/shared/useIsHomePage';
import analytics, { EventType } from '@src/app/analytics';
import { resolveRuntimePath } from '@src/utils/runtimeBasePath';

const AVENEWS_LOGO_SRC = resolveRuntimePath('/assets/logos/avenews-logo.png');

const Container = styled.div`
    display: flex;
    width: 100%;
    height: 40px;
    min-height: 40px;
    align-items: center;
    gap: 8px;
    margin-left: -3px;
`;

const BrandLogo = styled.img<{ $collapsed: boolean }>`
    display: block;
    height: ${({ $collapsed }) => ($collapsed ? '26px' : '28px')};
    max-height: ${({ $collapsed }) => ($collapsed ? '26px' : '28px')};
    width: auto;
    max-width: ${({ $collapsed }) => ($collapsed ? '36px' : '100%')};
    object-fit: contain;
`;

const StyledLink = styled(Link)`
    display: flex;
    height: 40px;
    align-items: center;
    justify-content: center;
    max-width: calc(100% - 40px);
    width: 100%;
    gap: 8px;
`;

type Props = {
    logotype?: React.ReactElement;
};

export default function NavBarHeader(_props: Props) {
    const { toggle, isCollapsed } = useNavBarContext();
    const showHomepageRedesign = useShowHomePageRedesign();
    const isHomePage = useIsHomePage();

    function handleLogoClick() {
        if (isHomePage && showHomepageRedesign) {
            toggle();
        }
        analytics.event({ type: EventType.NavBarItemClick, label: 'Home' });
    }

    return (
        <Container>
            <StyledLink to="/" onClick={handleLogoClick} data-testid="nav-bar-home-logo">
                <BrandLogo src={AVENEWS_LOGO_SRC} alt="Avenews" $collapsed={isCollapsed} />
            </StyledLink>
            {!isCollapsed && <NavBarToggler />}
        </Container>
    );
}
